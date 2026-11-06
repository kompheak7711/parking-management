// General Ledger phase 6 step 6: the words of the ledger screens, in English and Khmer, from
// the mock-up (i18n22.js, i18n26.js, i18n29.js, i18n34.js). Khmer marked "new" is not in the
// mock-up and needs the native check, like every Khmer text before the app is used.

import type { Language } from "../signInText";
import type { AccountType } from "./ledgerClient";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: [
    "This list could not be read just now.",
    "មិនអាចអានបញ្ជីនេះបានទេឥឡូវនេះ។",
  ],
  retry: ["Try again", "សាកម្តងទៀត"],
  no_property: ["Choose the Property first.", "សូមជ្រើសរើសអចលនទ្រព្យជាមុនសិន។"],
  cancel: ["Cancel", "បោះបង់"],
  close: ["Close", "បិទ"],
  save: ["Save", "រក្សាទុក"],
  required: ["Required", "ត្រូវការ"],
  back: ["Back", "ត្រឡប់ក្រោយ"],
  // new
  f_right: [
    "You do not have the right to do this.",
    "អ្នកមិនមានសិទ្ធិធ្វើការនេះទេ។",
  ],
  // new
  f_failed: ["This was not saved. Try again.", "មិនបានរក្សាទុកទេ។ សាកម្តងទៀត។"],
  // new
  f_refused: ["The app refused this: {0}", "កម្មវិធីបានបដិសេធ៖ {0}"],
  // new
  not_found: [
    "This entry is not in the ledger.",
    "ធាតុនេះមិនមាននៅក្នុងសៀវភៅបញ្ជីទេ។",
  ],
  // Journal entries
  j_title: ["Journal entries", "ធាតុទិនានុប្បវត្តិ"],
  j_sub: [
    "Every money record makes its own balanced entry by itself. Entries are never edited; a mistake gets a reversing entry.",
    "កំណត់ត្រាប្រាក់នីមួយៗបង្កើតធាតុដែលមានតុល្យភាពដោយខ្លួនឯង។ ធាតុមិនត្រូវកែទេ។ កំហុសត្រូវមានធាតុបញ្ច្រាស។",
  ],
  month: ["Month", "ខែ"],
  all_months: ["All months", "គ្រប់ខែ"],
  no: ["No.", "លេខ"],
  date: ["Date", "កាលបរិច្ឆេទ"],
  what: ["What happened", "អ្វីបានកើតឡើង"],
  from: ["From", "ពី"],
  amount: ["Amount", "ចំនួន"],
  debit: ["Debit", "ឥណពន្ធ"],
  credit: ["Credit", "ឥណទាន"],
  account: ["Account", "គណនី"],
  balance: ["Balance", "សមតុល្យ"],
  total: ["Total", "សរុប"],
  newest: [
    "Newest {0} entries. Pick a month to see all of it.",
    "ធាតុថ្មីបំផុត {0}។ ជ្រើសខែ ដើម្បីមើលទាំងអស់។",
  ],
  // new
  j_none: [
    "No journal entries yet. The ledger starts on 1 January 2027.",
    "មិនទាន់មានធាតុទិនានុប្បវត្តិទេ។ សៀវភៅបញ្ជីចាប់ផ្ដើមថ្ងៃទី១ ខែមករា ឆ្នាំ២០២៧។",
  ],
  balanced: ["Balanced", "មានតុល្យភាព"],
  je_note: [
    "This entry is never edited. To fix a mistake, reverse it and record it again.",
    "ធាតុនេះមិនត្រូវកែទេ។ ដើម្បីកែកំហុស សូមបញ្ច្រាស ហើយកត់ត្រាម្ដងទៀត។",
  ],
  rev_ctl: [
    "Entries made from app records are fixed through the record itself (void, correction).",
    "ធាតុពីកំណត់ត្រាកម្មវិធីត្រូវកែតាមកំណត់ត្រានោះ (លុបចោល ការកែតម្រូវ)។",
  ],
  rev_done: ["Reversed by {0}", "បានបញ្ច្រាសដោយ {0}"],
  rev_of: ["Reverses {0}", "បញ្ច្រាស {0}"],
  posted_by: ["Recorded by", "កត់ត្រាដោយ"],
  // new
  app: ["The app", "កម្មវិធី"],
  // new
  approved_by: ["Approved by", "អនុម័តដោយ"],
  // new
  reason: ["Reason", "មូលហេតុ"],
  // new
  closed_month: ["Its month is closed.", "ខែរបស់វាបានបិទ។"],
  // Entry kinds (mock-up gl_k_*)
  k_AUTO: ["From an app record", "ពីកំណត់ត្រាកម្មវិធី"],
  k_RENT_TO_INCOME: ["Rent moves to income", "ឈ្នួលចូលចំណូល"],
  k_DEPRECIATION: ["Depreciation", "រំលោះ"],
  k_FX_REVALUATION: [
    "Riel cash valued at month end",
    "វាយតម្លៃសាច់ប្រាក់រៀលចុងខែ",
  ],
  k_OPENING: ["Opening balance", "សមតុល្យដើម"],
  k_ADJUSTING: ["Adjusting entry", "ធាតុកែតម្រូវ"],
  k_REVERSAL: ["Reversal", "ការបញ្ច្រាស"],
  k_YEAR_END_CLOSE: ["Year-end close", "បិទចុងឆ្នាំ"],
  // Record kinds (source types)
  s_INVOICE: ["Invoice issued", "វិក្កយបត្រចេញ"],
  s_INVOICE_LINE: ["Invoice line", "បន្ទាត់វិក្កយបត្រ"],
  s_INVOICE_ADJUSTMENT: ["Invoice corrected", "វិក្កយបត្របានកែ"],
  s_LATE_PAYMENT_CHARGE: ["Late-payment charge", "ថ្លៃបង់យឺត"],
  s_LATE_PAYMENT_CHARGE_CORRECTION: [
    "Late-payment charge corrected",
    "ថ្លៃបង់យឺតបានកែ",
  ],
  s_PAYMENT: ["Payment received", "ការបង់ប្រាក់បានទទួល"],
  s_PAYMENT_ALLOCATION: [
    "Payment used for an Invoice",
    "ប្រាក់ប្រើសម្រាប់វិក្កយបត្រ",
  ],
  s_DEPOSIT_RECEIPT: ["Deposit received", "ប្រាក់កក់បានទទួល"],
  s_DEPOSIT_APPLICATION: ["Deposit used", "ប្រាក់កក់បានប្រើ"],
  s_DEPOSIT_DISPOSITION: ["Deposit kept or returned", "ប្រាក់កក់រក្សាទុក ឬសង"],
  s_CUSTOMER_CREDIT: ["Customer Credit", "ឥណទានអតិថិជន"],
  s_CREDIT_APPLICATION: ["Customer Credit used", "ឥណទានអតិថិជនបានប្រើ"],
  s_REFUND: ["Refund paid", "ការសងប្រាក់"],
  s_REFUND_CORRECTION: ["Refund correction", "ការកែការសងប្រាក់"],
  s_EXPENSE: ["Expense", "ចំណាយ"],
  s_EXPENSE_REQUEST: ["Staff advance", "ប្រាក់បុរេប្រទានបុគ្គលិក"],
  s_STAFF_PAYBACK: ["Staff paid back", "សងប្រាក់បុគ្គលិក"],
  s_BILL_PAYMENT: ["Supplier bill paid", "វិក្កយបត្រអ្នកផ្គត់ផ្គង់បានបង់"],
  s_MONEY_MOVE: ["Money moved", "ផ្ទេរប្រាក់"],
  s_SHORT_STAY_DEPOSIT: ["Short-stay deposit", "ប្រាក់កក់ស្នាក់នៅខ្លី"],
  s_OWNER_MONEY: ["Owner money", "ប្រាក់ម្ចាស់"],
  s_PETTY_CASH_TOPUP: ["Petty cash top-up", "បំពេញសាច់ប្រាក់រាយ"],
  s_CASH_COUNT: ["Cash count difference", "ភាពខុសគ្នានៃការរាប់សាច់ប្រាក់"],
  // Chart of accounts
  a_title: ["Chart of accounts", "តារាងគណនី"],
  a_sub: [
    "The chart of accounts. Only the Owner adds accounts. An account with entries is turned off, never deleted.",
    "តារាងគណនី។ មានតែម្ចាស់ទេដែលបន្ថែមគណនីបាន។ គណនីដែលមានធាតុត្រូវបិទ មិនលុបចោលទេ។",
  ],
  code: ["Code", "លេខកូដ"],
  t_ASSET: ["Assets", "ទ្រព្យសកម្ម"],
  t_LIABILITY: ["Liabilities", "បំណុល"],
  t_EQUITY: ["Owner's equity", "មូលធនម្ចាស់"],
  t_INCOME: ["Income", "ចំណូល"],
  t_COST_OF_SALES: ["Cost of products sold", "ថ្លៃដើមផលិតផលលក់"],
  t_EXPENSE: ["Expenses", "ចំណាយ"],
  ctl: ["App records only", "តែកំណត់ត្រាកម្មវិធី"],
  ctl_s: [
    "Changes only through app records, so the books always match the app.",
    "ប្ដូរតែតាមកំណត់ត្រាកម្មវិធី ដូច្នេះសៀវភៅតែងតែត្រូវនឹងកម្មវិធី។",
  ],
  off: ["Turned off", "បានបិទ"],
  tax: ["No entries yet", "មិនទាន់មានធាតុ"],
  tax_n: [
    "No entries until a tax agent confirms the rules.",
    "មិនមានធាតុរហូតដល់ភ្នាក់ងារពន្ធបញ្ជាក់ច្បាប់។",
  ],
  off_n: [
    "This account is turned off. Old entries stay. No new entries can use it.",
    "គណនីនេះបានបិទ។ ធាតុចាស់នៅដដែល។ ធាតុថ្មីមិនអាចប្រើវាបានទេ។",
  ],
  used_n: [
    "This account has entries, so it can be turned off but never deleted.",
    "គណនីនេះមានធាតុ ដូច្នេះអាចបិទបាន តែមិនអាចលុបបានទេ។",
  ],
  ad_sub: [
    "Every entry in this account, newest first, with the balance after each one.",
    "ធាតុទាំងអស់ក្នុងគណនីនេះ ថ្មីមុន ជាមួយសមតុល្យក្រោយនីមួយៗ។",
  ],
  // new
  ad_open: ["Opening balance", "សមតុល្យដើម"],
  // Needs check
  nc_title: ["Needs check", "ត្រូវពិនិត្យ"],
  nc_sub: [
    "App money records that could not go to the ledger yet",
    "កំណត់ត្រាប្រាក់ក្នុងកម្មវិធីដែលមិនទាន់ចូលសៀវភៅបញ្ជីបាន",
  ],
  nc_open: ["To fix", "ត្រូវកែ"],
  nc_record: ["Record", "កំណត់ត្រា"],
  nc_reason: ["Reason", "មូលហេតុ"],
  nc_none: [
    "Nothing to check. Every money record is in the ledger.",
    "គ្មានអ្វីត្រូវពិនិត្យទេ។ កំណត់ត្រាប្រាក់ទាំងអស់នៅក្នុងសៀវភៅបញ្ជី។",
  ],
  nc_note: [
    "Nothing is lost: each record goes to the ledger as soon as its reason is fixed. A Refund corrected after it was paid posts by itself; it shows here only when its Refund method has no ledger account.",
    "គ្មានអ្វីបាត់ទេ៖ កំណត់ត្រានីមួយៗចូលសៀវភៅបញ្ជីភ្លាម ពេលកែមូលហេតុរួច។ ការសងប្រាក់ដែលកែក្រោយបានសង ចូលសៀវភៅបញ្ជីដោយខ្លួនឯង; វាបង្ហាញនៅទីនេះតែពេលមធ្យោបាយសងប្រាក់គ្មានគណនីសៀវភៅបញ្ជីប៉ុណ្ណោះ។",
  ],
  nc_r_pay: [
    "No ledger account is set for the Payment Method {0}",
    "មិនទាន់កំណត់គណនីសៀវភៅបញ្ជីសម្រាប់មធ្យោបាយបង់ប្រាក់ {0}",
  ],
  nc_r_refund: [
    "No ledger account is set for the Refund method {0}",
    "មិនទាន់កំណត់គណនីសៀវភៅបញ្ជីសម្រាប់មធ្យោបាយសងប្រាក់ {0}",
  ],
  // new
  nc_r_other: [
    "The ledger could not post this record. It tries again after each change; if it stays here, tell the person who set up the app.",
    "សៀវភៅបញ្ជីមិនអាចកត់ត្រាកំណត់ត្រានេះបានទេ។ វាសាកម្ដងទៀតក្រោយការផ្លាស់ប្ដូរនីមួយៗ; បើវានៅតែនៅទីនេះ សូមប្រាប់អ្នកដែលរៀបចំកម្មវិធី។",
  ],
  nc_set: ["Set the account", "កំណត់គណនី"],
  nc_set_m: ["Set the method's account", "កំណត់គណនីរបស់មធ្យោបាយ"],
  nc_change: ["Change", "ប្ដូរ"],
  nc_macc: ["Payment Method accounts", "គណនីមធ្យោបាយបង់ប្រាក់"],
  nc_macc_s: [
    "Which cash or bank account each Payment Method uses in the ledger.",
    "គណនីសាច់ប្រាក់ ឬធនាគារដែលមធ្យោបាយបង់ប្រាក់នីមួយៗប្រើក្នុងសៀវភៅបញ្ជី។",
  ],
  // new
  nc_racc: ["Refund method accounts", "គណនីមធ្យោបាយសងប្រាក់"],
  nc_method: ["Payment Method", "មធ្យោបាយបង់ប្រាក់"],
  // new
  nc_rmethod: ["Refund method", "មធ្យោបាយសងប្រាក់"],
  nc_notset: ["Not set", "មិនទាន់កំណត់"],
  nc_owner_only: [
    "Only the Owner sets these accounts.",
    "មានតែម្ចាស់ទេដែលកំណត់គណនីទាំងនេះ។",
  ],
  nc_acc_t: ["Ledger account for {0}", "គណនីសៀវភៅបញ្ជីសម្រាប់ {0}"],
  nc_acc_future: [
    "New payments with this method use this account from now on.",
    "ការបង់ប្រាក់ថ្មីតាមមធ្យោបាយនេះប្រើគណនីនេះចាប់ពីឥឡូវ។",
  ],
  // new
  nc_from: ["From", "ចាប់ពី"],
  // new
  nc_since: ["since {0}", "ចាប់ពី {0}"],
  // new
  nc_saved: ["{0} now uses account {1}.", "{0} ឥឡូវប្រើគណនី {1}។"],
  // Riel bank account (owner 04/11/2026)
  nc_riel: ["Riel account", "គណនីរៀល"],
  nc_riel_none: ["None", "គ្មាន"],
  nc_riel_h: [
    "A payment in riel goes to this account. With none, riel paid by a dollar cash method goes to 1011, and other riel goes to the account above.",
    "ការបង់ប្រាក់ជារៀលចូលគណនីនេះ។ បើគ្មាន រៀលដែលបង់តាមមធ្យោបាយសាច់ប្រាក់ដុល្លារចូល ១០១១ ហើយរៀលផ្សេងទៀតចូលគណនីខាងលើ។",
  ],
  nc_riel_line: ["Riel: {0}", "រៀល៖ {0}"],
  // Refund paid from a riel account (owner 05/11/2026, DL-161)
  nc_r_riel: [
    "Paid from a riel account: type the riel that left it. The tenant still got dollars.",
    "បានសងពីគណនីរៀល៖ វាយបញ្ចូលចំនួនរៀលដែលចេញពីគណនីនោះ។ អ្នកជួលនៅតែទទួលបានដុល្លារ។",
  ],
  nc_r_ready: [
    "Fixed. It goes to the ledger at the next posting run.",
    "បានកែរួច។ វានឹងចូលសៀវភៅបញ្ជីនៅពេលកត់ត្រាលើកក្រោយ។",
  ],
  nc_r_rcorr: [
    "A correction of a Refund paid from a riel account. It cannot go to the ledger yet; it waits for a later version of the app.",
    "ការកែការសងប្រាក់ដែលបានសងពីគណនីរៀល។ វាមិនទាន់អាចចូលសៀវភៅបញ្ជីបានទេ; វារង់ចាំកំណែក្រោយរបស់កម្មវិធី។",
  ],
  nc_riel_type: ["Type the riel", "វាយបញ្ចូលរៀល"],
  nc_rr_t: ["Riel paid for {0}", "រៀលដែលបានសងសម្រាប់ {0}"],
  nc_rr_amt: ["Riel paid (៛)", "រៀលដែលបានសង (៛)"],
  nc_rr_h: [
    "Whole riel, as on the bank slip. Type it once: it cannot be changed later.",
    "ចំនួនរៀលគត់ ដូចលើបង្កាន់ដៃធនាគារ។ វាយបញ្ចូលតែម្ដង៖ មិនអាចប្ដូរក្រោយបានទេ។",
  ],
  nc_rr_bad: [
    "Type the riel as a whole number, more than 0.",
    "វាយបញ្ចូលរៀលជាចំនួនគត់ ធំជាង ០។",
  ],
  nc_rr_saved: [
    "The riel for {0} is saved. It goes to the ledger at the next posting run.",
    "រៀលសម្រាប់ {0} បានរក្សាទុក។ វានឹងចូលសៀវភៅបញ្ជីនៅពេលកត់ត្រាលើកក្រោយ។",
  ],
  nc_racc_h: [
    "To pay Refunds from the riel bank account, choose 1021. The Refund stays in dollars; you then type the riel paid in Needs check.",
    "ដើម្បីសងប្រាក់ពីគណនីធនាគាររៀល សូមជ្រើស ១០២១។ ការសងប្រាក់នៅតែជាដុល្លារ; បន្ទាប់មកអ្នកវាយបញ្ចូលរៀលដែលបានសងនៅក្នុង ត្រូវពិនិត្យ។",
  ],
  // Financial statements
  r_title: ["Financial statements", "របាយការណ៍ហិរញ្ញវត្ថុ"],
  r_sub: [
    "Made from the journal entries. Pick a statement and a month.",
    "បង្កើតពីធាតុទិនានុប្បវត្តិ។ ជ្រើសរបាយការណ៍ និងខែ។",
  ],
  r_profit_and_loss: ["Profit and loss", "ចំណេញ និងខាត"],
  r_balance_sheet: ["Balance sheet", "តារាងតុល្យការ"],
  r_cash_flow: ["Cash flow", "លំហូរសាច់ប្រាក់"],
  r_trial_balance: ["Trial balance", "តុល្យភាពសាកល្បង"],
  r_account_detail: ["Account detail", "ព័ត៌មានលម្អិតគណនី"],
  r_customer_aging: ["Customer debt aging", "អាយុបំណុលអតិថិជន"],
  r_bills_aging: ["Supplier bill aging", "អាយុវិក្កយបត្រអ្នកផ្គត់ផ្គង់"],
  r_budget: ["Budget vs actual", "ថវិកាធៀបនឹងជាក់ស្ដែង"],
  r_books_check: ["Books check", "ការត្រួតពិនិត្យសៀវភៅ"],
  xlsx: ["Export Excel", "នាំចេញ Excel"],
  pdf: ["Export PDF (A4)", "នាំចេញ PDF (A4)"],
  st_closed: ["Closed", "បានបិទ"],
  st_open: ["Open, may still change", "បើក អាចនៅប្ដូរ"],
  // new
  st_today: ["As at today", "គិតត្រឹមថ្ងៃនេះ"],
  ok: ["Matches", "ត្រូវគ្នា"],
  bad: ["Does not match", "មិនត្រូវគ្នា"],
  // new
  as_of: ["As at", "គិតត្រឹម"],
  // new
  to: ["To", "ដល់"],
  // new
  r_none: ["Nothing to show.", "គ្មានអ្វីត្រូវបង្ហាញទេ។"],
  // new
  r_check: ["Check", "ការត្រួតពិនិត្យ"],
  // new
  r_english: [
    "Statement words come from the ledger in English; account names follow your language.",
    "ពាក្យក្នុងរបាយការណ៍មកពីសៀវភៅបញ្ជីជាភាសាអង់គ្លេស ឈ្មោះគណនីតាមភាសារបស់អ្នក។",
  ],
  // new
  x_done: ["Downloaded {0}.", "បានទាញយក {0}។"],
  // Books check lines (gl_books_check)
  bc_CUSTOMER_DEBT: [
    "Customer debt (1100 + 1110) equals the unpaid Invoices and late-payment charges",
    "បំណុលអតិថិជន (1100 + 1110) ស្មើវិក្កយបត្រ និងថ្លៃបង់យឺតមិនទាន់បង់",
  ],
  bc_RENT_IN_ADVANCE: [
    "Rent billed in advance (2050) equals the app's list",
    "ឈ្នួលចេញវិក្កយបត្រជាមុន (2050) ស្មើបញ្ជីក្នុងកម្មវិធី",
  ],
  bc_SECURITY_DEPOSITS: [
    "Security Deposits held (2100) equals the app's list",
    "ប្រាក់កក់ធានាដែលកាន់ (2100) ស្មើបញ្ជីក្នុងកម្មវិធី",
  ],
  bc_PET_DEPOSITS: [
    "Pet Deposits held (2110) equals the app's list",
    "ប្រាក់កក់សត្វចិញ្ចឹម (2110) ស្មើបញ្ជីក្នុងកម្មវិធី",
  ],
  bc_CUSTOMER_CREDIT: [
    "Customer Credit (2200) equals the app's list",
    "ឥណទានអតិថិជន (2200) ស្មើបញ្ជីក្នុងកម្មវិធី",
  ],
  bc_MONEY_NOT_USED: [
    "Money not used yet (2210) equals the app's list",
    "ប្រាក់មិនទាន់ប្រើ (2210) ស្មើបញ្ជីក្នុងកម្មវិធី",
  ],
  bc_EVERY_RECORD_POSTED: [
    "Every app money record has its entry",
    "កំណត់ត្រាប្រាក់ក្នុងកម្មវិធីនីមួយៗមានធាតុរបស់វា",
  ],
  bc_EVERY_ENTRY_BALANCED: ["Every entry is balanced", "ធាតុនីមួយៗមានតុល្យភាព"],
  // new
  bc_in_books: ["In the books", "ក្នុងសៀវភៅ"],
  // new
  bc_in_app: ["In the app", "ក្នុងកម្មវិធី"],
  // new
  bc_waiting: ["{0} waiting", "{0} កំពុងរង់ចាំ"],
  // Part 2: Expense requests, Expenses, Supplier bills (i18n24.js, i18n26.js)
  er_t: ["Expense requests", "សំណើចំណាយ"],
  er_sub: [
    "Staff ask before they spend. For urgent spending, staff pay first and send an Expense report with the bill.",
    "បុគ្គលិកស្នើមុនពេលចំណាយ។ ចំណាយបន្ទាន់ បុគ្គលិកបង់មុន ហើយផ្ញើរបាយការណ៍ចំណាយជាមួយវិក្កយបត្រ។",
  ],
  er_new: ["New Expense request", "សំណើចំណាយថ្មី"],
  er_new_rep: ["New Expense report", "របាយការណ៍ចំណាយថ្មី"],
  er_req: ["Expense request", "សំណើចំណាយ"],
  er_rep: ["Expense report", "របាយការណ៍ចំណាយ"],
  er_open_t: ["Open requests and advances", "សំណើ និងប្រាក់បុរេប្រទានដែលនៅបើក"],
  er_c_wait: ["Waiting for approval", "រង់ចាំការអនុម័ត"],
  er_c_adv: ["Advances not cleared", "ប្រាក់បុរេប្រទានមិនទាន់ជម្រះ"],
  er_c_late: ["Late reports", "របាយការណ៍យឺត"],
  er_c_owed: ["Money owed to staff", "ប្រាក់ជំពាក់បុគ្គលិក"],
  er_c_all: ["All requests", "សំណើទាំងអស់"],
  er_c_n: ["{0} open", "{0} នៅបើក"],
  er_list_open: ["Open requests", "សំណើដែលនៅបើក"],
  er_c_late_s: [
    "Bill not back after {0} days",
    "វិក្កយបត្រមិនទាន់មកវិញក្រោយ {0} ថ្ងៃ",
  ],
  er_c_owed_s: ["To pay back", "ត្រូវសងវិញ"],
  er_no: ["Number", "លេខ"],
  er_date: ["Date", "កាលបរិច្ឆេទ"],
  er_date_spent: ["Date spent", "ថ្ងៃចំណាយ"],
  er_urgent: ["Urgent", "បន្ទាន់"],
  er_u_no: ["No: ask before spending", "ទេ៖ ស្នើមុនពេលចំណាយ"],
  er_u_yes: [
    "Yes: already spent, this is an Expense report",
    "បាទ/ចាស៖ បានចំណាយរួច នេះជារបាយការណ៍ចំណាយ",
  ],
  er_for: ["What for", "សម្រាប់អ្វី"],
  er_why: ["Reason", "មូលហេតុ"],
  er_amt: ["Amount", "ចំនួនទឹកប្រាក់"],
  er_sup: ["Supplier (if known)", "អ្នកផ្គត់ផ្គង់ (បើដឹង)"],
  er_sup_s: ["Supplier", "អ្នកផ្គត់ផ្គង់"],
  er_unit: ["Unit", "បន្ទប់"],
  er_unit_h: [
    "For repairs only, so you can see what each Unit costs in repairs.",
    "សម្រាប់ការជួសជុលប៉ុណ្ណោះ ដើម្បីមើលថ្លៃជួសជុលរបស់បន្ទប់នីមួយៗ។",
  ],
  er_unit_none: ["Whole building (no Unit)", "អគារទាំងមូល (គ្មានបន្ទប់)"],
  er_c_open: ["Show all open", "បង្ហាញទាំងអស់ដែលបើក"],
  er_from: ["Paid from", "បង់ពី"],
  er_f_ADV: ["Advance to staff", "ប្រាក់បុរេប្រទានឱ្យបុគ្គលិក"],
  er_f_OWN: ["Staff's own money", "ប្រាក់ផ្ទាល់ខ្លួនបុគ្គលិក"],
  er_f_LATER: [
    "Pay later (supplier bill)",
    "បង់ពេលក្រោយ (វិក្កយបត្រអ្នកផ្គត់ផ្គង់)",
  ],
  er_cur: ["Currency", "រូបិយប័ណ្ណ"],
  er_rate: ["= {0} at {1} ៛ per $1", "= {0} តាមអត្រា {1} ៛ ក្នុង $1"],
  er_asset_h: [
    "From {0}, choose an asset account (business rule).",
    "ចាប់ពី {0} សូមជ្រើសគណនីទ្រព្យសកម្ម (ច្បាប់អាជីវកម្ម)។",
  ],
  er_who_acct: [
    "Approved by: the Accountant (up to {0}) or the Owner.",
    "អនុម័តដោយ៖ គណនេយ្យករ (រហូតដល់ {0}) ឬម្ចាស់។",
  ],
  er_who_own: [
    "Approved by: the Owner (above {0}).",
    "អនុម័តដោយ៖ ម្ចាស់ (លើស {0})។",
  ],
  er_late_n: [
    "This report is late. It was due on {0} ({1} days after spending, business rule).",
    "របាយការណ៍នេះយឺត។ ត្រូវផុតកំណត់នៅ {0} ({1} ថ្ងៃក្រោយចំណាយ ច្បាប់អាជីវកម្ម)។",
  ],
  er_due_n: [
    "Send the Expense report with the bill within {0} days of spending (business rule).",
    "ផ្ញើរបាយការណ៍ចំណាយជាមួយវិក្កយបត្រក្នុងរយៈពេល {0} ថ្ងៃក្រោយចំណាយ (ច្បាប់អាជីវកម្ម)។",
  ],
  er_e_why: ["Write why this is needed.", "សូមសរសេរហេតុផល។"],
  er_e_amt: ["Type the amount.", "សូមវាយចំនួនទឹកប្រាក់។"],
  er_e_date: [
    "Type a date as dd/mm/yyyy, not after today.",
    "វាយកាលបរិច្ឆេទជា dd/mm/yyyy មិនក្រោយថ្ងៃនេះ។",
  ],
  er_send: ["Send", "ផ្ញើ"],
  er_sent: [
    "{0} sent. It waits for approval.",
    "បានផ្ញើ {0}។ រង់ចាំការអនុម័ត។",
  ],
  er_st_WAITING: ["Waiting for approval", "រង់ចាំការអនុម័ត"],
  er_st_APPROVED: ["Approved", "បានអនុម័ត"],
  er_st_PAID_OUT: ["Advance given", "បានផ្ដល់ប្រាក់បុរេប្រទាន"],
  er_st_DONE: ["Done", "រួចរាល់"],
  er_st_VOID: ["Void", "ទុកជាមោឃៈ"],
  er_late: ["Late", "យឺត"],
  er_owed: ["Owed to staff", "ជំពាក់បុគ្គលិក"],
  er_details: ["Details", "ព័ត៌មានលម្អិត"],
  er_steps: ["Steps", "ជំហាន"],
  er_need: ["Who approves", "អ្នកអនុម័ត"],
  er_s_sent: ["Sent by {0}", "ផ្ញើដោយ {0}"],
  er_s_ok: ["Approved by {0}", "អនុម័តដោយ {0}"],
  er_s_adv: [
    "Advance of {0} given by {1} from {2}",
    "ប្រាក់បុរេប្រទាន {0} ផ្ដល់ដោយ {1} ពី {2}",
  ],
  er_s_bill: ["Bill of {0} recorded by {1}", "វិក្កយបត្រ {0} កត់ត្រាដោយ {1}"],
  er_s_change: ["Change returned: {0}", "ប្រាក់អាប់ប្រគល់វិញ៖ {0}"],
  er_s_extra: [
    "Staff paid {0} more; it is owed to them.",
    "បុគ្គលិកបង់លើស {0} ដែលត្រូវសងពួកគេ។",
  ],
  er_s_back: ["{0} paid back to {1} by {2}", "សង {0} ទៅ {1} ដោយ {2}"],
  er_s_void: ["Void by {0}: {1}", "ទុកជាមោឃៈដោយ {0}៖ {1}"],
  er_s_entry: ["Entry {0}", "ធាតុ {0}"],
  er_approve: ["Approve", "អនុម័ត"],
  er_void: ["Void", "ទុកជាមោឃៈ"],
  er_give: ["Give advance", "ផ្ដល់ប្រាក់បុរេប្រទាន"],
  er_bill: ["Record bill", "កត់ត្រាវិក្កយបត្រ"],
  er_payback: ["Pay back staff", "សងប្រាក់បុគ្គលិក"],
  er_wait_own: [
    "Waits for the Owner: the amount is above the Expense limit of {0}.",
    "រង់ចាំម្ចាស់៖ ចំនួនលើសកម្រិតចំណាយ {0}។",
  ],
  er_wait_any: [
    "Waits for the Accountant or the Owner.",
    "រង់ចាំគណនេយ្យករ ឬម្ចាស់។",
  ],
  er_ok_t: ["Approve {0}?", "អនុម័ត {0}?"],
  er_ok_n: ["{0} for {1}. Requested by {2}.", "{0} សម្រាប់ {1}។ ស្នើដោយ {2}។"],
  er_ok_post: [
    "Approving this report records the expense in the books now.",
    "ការអនុម័តរបាយការណ៍នេះ កត់ត្រាចំណាយក្នុងសៀវភៅបញ្ជីឥឡូវនេះ។",
  ],
  er_ok_done: ["{0} approved.", "បានអនុម័ត {0}។"],
  er_void_t: ["Void {0}?", "ទុក {0} ជាមោឃៈ?"],
  er_void_n: [
    "A request is never edited. Void it with a reason, then send a new one.",
    "សំណើមិនត្រូវកែទេ។ ទុកជាមោឃៈដោយមានមូលហេតុ រួចផ្ញើសំណើថ្មី។",
  ],
  er_void_done: ["{0} is void.", "{0} ជាមោឃៈ។"],
  er_give_t: ["Give an advance for {0}", "ផ្ដល់ប្រាក់បុរេប្រទានសម្រាប់ {0}"],
  er_give_from: ["Pay the advance from", "បង់ប្រាក់បុរេប្រទានពី"],
  er_give_n: [
    "The staff member brings the bill and any change within {0} days (business rule).",
    "បុគ្គលិកនាំវិក្កយបត្រ និងប្រាក់អាប់មកវិញក្នុងរយៈពេល {0} ថ្ងៃ (ច្បាប់អាជីវកម្ម)។",
  ],
  er_give_done: [
    "Advance given. Entry {0}.",
    "បានផ្ដល់ប្រាក់បុរេប្រទាន។ ធាតុ {0}។",
  ],
  er_bill_t: ["Record the bill for {0}", "កត់ត្រាវិក្កយបត្រសម្រាប់ {0}"],
  er_bill_amt: ["Bill amount", "ចំនួនក្នុងវិក្កយបត្រ"],
  er_bill_ref: ["Reference", "លេខយោង"],
  er_bill_adv: ["Advance given: {0}.", "ប្រាក់បុរេប្រទានបានផ្ដល់៖ {0}។"],
  er_bill_done: [
    "Bill recorded as expense {0}. Entry {1}.",
    "បានកត់ត្រាវិក្កយបត្រជាចំណាយ {0}។ ធាតុ {1}។",
  ],
  er_back_t: ["Pay back {0}", "សងប្រាក់ {0}"],
  er_back_from: ["Pay from", "បង់ពី"],
  er_back_done: ["Paid back. Entry {0}.", "បានសងវិញ។ ធាតុ {0}។"],
  er_you: ["You are signed in as {0}, {1}.", "អ្នកបានចូលជា {0}, {1}។"],
  er_can_all: ["You approve every request.", "អ្នកអនុម័តសំណើទាំងអស់។"],
  er_can_lim: [
    "You approve requests up to {0}. Above that, the Owner approves.",
    "អ្នកអនុម័តសំណើរហូតដល់ {0}។ លើសនេះ ម្ចាស់អនុម័ត។",
  ],
  er_can_pay: [
    "You give advances, record bills and pay staff back.",
    "អ្នកផ្ដល់ប្រាក់បុរេប្រទាន កត់ត្រាវិក្កយបត្រ និងសងប្រាក់បុគ្គលិក។",
  ],
  er_can_send: [
    "You send Expense requests and reports. You cannot approve or pay money.",
    "អ្នកផ្ញើសំណើ និងរបាយការណ៍ចំណាយ។ អ្នកមិនអាចអនុម័ត ឬបង់ប្រាក់បានទេ។",
  ],
  er_next: ["Your next step", "ជំហានបន្ទាប់របស់អ្នក"],
  er_n_owner: ["Waits for the Owner", "រង់ចាំម្ចាស់"],
  er_n_wait: ["Waits for approval", "រង់ចាំការអនុម័ត"],
  er_n_acct: ["Accountant's step", "ជំហានរបស់គណនេយ្យករ"],
  er_for_you: ["{0} for you", "{0} សម្រាប់អ្នក"],
  er_none: ["No requests here.", "គ្មានសំណើនៅទីនេះទេ។"],
  er_from_req: ["From request", "ពីសំណើ"],
  er_cant: [
    "You can see this request. Approving and paying are done by the Accountant or the Owner.",
    "អ្នកអាចមើលសំណើនេះ។ ការអនុម័ត និងការបង់ប្រាក់ធ្វើដោយគណនេយ្យករ ឬម្ចាស់។",
  ],
  er_owed_line: ["Pay back {0}: {1}", "សងប្រាក់ {0}៖ {1}"],
  er_n_self: ["Someone else must approve", "អ្នកផ្សេងត្រូវអនុម័ត"],
  er_wait_self: [
    "You sent this request. Someone else must approve it.",
    "អ្នកបានផ្ញើសំណើនេះ។ អ្នកផ្សេងត្រូវអនុម័តវា។",
  ],
  er_own: ["Owner's own spending", "ការចំណាយផ្ទាល់របស់ម្ចាស់"],
  er_own_n: [
    "Approved at once: the Owner's own spending, kept with this note.",
    "បានអនុម័តភ្លាម៖ ការចំណាយផ្ទាល់របស់ម្ចាស់ រក្សាទុកជាមួយកំណត់សម្គាល់នេះ។",
  ],
  er_own_only: [
    "You see only your own requests.",
    "អ្នកឃើញតែសំណើរបស់អ្នកប៉ុណ្ណោះ។",
  ],
  gl_x_limit: [
    "An Expense request above {0} is approved by the Owner; up to {0}, by the Accountant (business rule).",
    "សំណើចំណាយលើស {0} អនុម័តដោយម្ចាស់ រហូតដល់ {0} ដោយគណនេយ្យករ (ច្បាប់អាជីវកម្ម)។",
  ],
  col_status: ["Status", "ស្ថានភាព"],
  x_title: ["Expenses", "ចំណាយ"],
  x_sub: [
    "Bills and costs of the business. Monthly bills such as EDC, water and internet are recorded here straight. Other spending starts with an Expense request. Never edited: void with a reason, then record again.",
    "វិក្កយបត្រ និងថ្លៃចំណាយរបស់អាជីវកម្ម។ វិក្កយបត្រប្រចាំខែ ដូចជា EDC ទឹក និងអ៊ីនធឺណិត កត់ត្រានៅទីនេះផ្ទាល់។ ចំណាយផ្សេងទៀតចាប់ផ្ដើមដោយសំណើចំណាយ។ មិនត្រូវកែទេ៖ ទុកជាមោឃៈដោយមានមូលហេតុ រួចកត់ត្រាម្ដងទៀត។",
  ],
  x_new: ["Record a bill", "កត់ត្រាវិក្កយបត្រ"],
  x_sup: ["Supplier", "អ្នកផ្គត់ផ្គង់"],
  x_for: ["Expense account", "គណនីចំណាយ"],
  x_from: ["Paid from", "បង់ពី"],
  x_ref: ["Reference", "លេខយោង"],
  x_later: [
    "Pay later (supplier bill)",
    "បង់ពេលក្រោយ (វិក្កយបត្រអ្នកផ្គត់ផ្គង់)",
  ],
  x_e_sup: ["Type the supplier.", "សូមវាយអ្នកផ្គត់ផ្គង់។"],
  x_e_amt: ["Type the amount.", "សូមវាយចំនួន។"],
  x_saved: [
    "Expense {0} recorded. Entry {1}.",
    "បានកត់ត្រាចំណាយ {0}។ ធាតុ {1}។",
  ],
  x_st_POSTED: ["Posted", "បានកត់"],
  sb_t: ["Supplier bills to pay", "វិក្កយបត្រអ្នកផ្គត់ផ្គង់ត្រូវបង់"],
  sb_sub: [
    "Bills from suppliers that we pay later. Each bill and each payment makes its own entry.",
    "វិក្កយបត្រពីអ្នកផ្គត់ផ្គង់ដែលយើងបង់ពេលក្រោយ។ វិក្កយបត្រ និងការបង់នីមួយៗបង្កើតធាតុរបស់ខ្លួន។",
  ],
  sb_new: ["Add supplier bill", "បន្ថែមវិក្កយបត្រអ្នកផ្គត់ផ្គង់"],
  sb_c_open: ["Still to pay", "នៅត្រូវបង់"],
  sb_c_n: ["{0} bills", "វិក្កយបត្រ {0}"],
  sb_c_late: ["Late", "យឺត"],
  sb_c_paid: ["Paid", "បានបង់"],
  sb_c_paid_s: ["Fully paid bills", "វិក្កយបត្របង់គ្រប់"],
  sb_l_open: ["Bills still to pay", "វិក្កយបត្រនៅត្រូវបង់"],
  sb_l_late: ["Late bills", "វិក្កយបត្រយឺត"],
  sb_l_paid: ["Paid bills", "វិក្កយបត្របានបង់"],
  sb_date: ["Bill date", "កាលបរិច្ឆេទវិក្កយបត្រ"],
  sb_due: ["Due date", "ថ្ងៃផុតកំណត់"],
  sb_left: ["Left to pay", "នៅសល់ត្រូវបង់"],
  sb_pay: ["Pay", "បង់"],
  sb_ref: ["Supplier's bill number", "លេខវិក្កយបត្រអ្នកផ្គត់ផ្គង់"],
  sb_st_paid: ["Paid", "បានបង់"],
  sb_st_late: ["{0} days late", "យឺត {0} ថ្ងៃ"],
  sb_st_open: ["Not yet due", "មិនទាន់ដល់ថ្ងៃ"],
  sb_note: [
    'Paid at once? Record it on Expenses. An expense marked "Pay later" comes here by itself, due 30 days after the bill date unless the bill shows its own due date (owner rule, 02/11/2026).',
    'បង់ភ្លាម? កត់ត្រានៅចំណាយ។ ចំណាយដែលសម្គាល់ "បង់ពេលក្រោយ" មកទីនេះដោយខ្លួនឯង ផុតកំណត់ ៣០ ថ្ងៃក្រោយកាលបរិច្ឆេទវិក្កយបត្រ លើកលែងតែវិក្កយបត្របង្ហាញថ្ងៃផុតកំណត់ផ្ទាល់ (ច្បាប់ម្ចាស់ ០២/១១/២០២៦)។',
  ],
  sb_e_due: [
    "The due date must be on or after the bill date.",
    "ថ្ងៃផុតកំណត់ត្រូវនៅថ្ងៃ ឬក្រោយកាលបរិច្ឆេទវិក្កយបត្រ។",
  ],
  sb_e_more: ["You can pay {0} or less.", "អ្នកអាចបង់ {0} ឬតិចជាងនេះ។"],
  sb_new_n: [
    "An item of {0} or more goes on Fixed assets, not here.",
    "របស់ដែលមានតម្លៃ {0} ឬច្រើនជាងនេះ ដាក់នៅទ្រព្យសកម្មរយៈពេលវែង មិនមែនទីនេះទេ។",
  ],
  sb_saved: [
    "Supplier bill {0} added. Entry {1}.",
    "បានបន្ថែមវិក្កយបត្រអ្នកផ្គត់ផ្គង់ {0}។ ធាតុ {1}។",
  ],
  sb_pay_t: ["Pay supplier bill {0}", "បង់វិក្កយបត្រអ្នកផ្គត់ផ្គង់ {0}"],
  sb_paid: ["Bill {0} paid. Entry {1}.", "បានបង់វិក្កយបត្រ {0}។ ធាតុ {1}។"],
  t_expenses: ["Expenses", "ចំណាយ"],
  t_assets: ["Assets", "ទ្រព្យសកម្ម"],
  // Part 2 words not in the mock-up
  // new
  er_st_REFUSED: ["Refused", "បានបដិសេធ"],
  // new
  er_not_found: [
    "This request is not there, or you cannot see it.",
    "សំណើនេះមិនមាន ឬអ្នកមិនអាចមើលវាបានទេ។",
  ],
  // new
  er_no_rate: [
    "There is no riel rate for today. Ask the Owner to set it in Settings.",
    "មិនមានអត្រារៀលសម្រាប់ថ្ងៃនេះទេ។ សូមស្នើម្ចាស់ឱ្យកំណត់វានៅក្នុងការកំណត់។",
  ],
  // new
  x_st_VOID: ["Void", "ទុកជាមោឃៈ"],
  // new
  x_no_unit: ["No Unit", "គ្មានបន្ទប់"],
  // new
  x_none: ["No expenses yet.", "មិនទាន់មានចំណាយទេ។"],
  // new
  sb_none: [
    "No supplier bills here.",
    "គ្មានវិក្កយបត្រអ្នកផ្គត់ផ្គង់នៅទីនេះទេ។",
  ],
  // new
  paid_on: ["Paid on", "បង់នៅថ្ងៃ"],
  // new
  by_unknown: ["Someone", "នរណាម្នាក់"],
  // Bank and cash (step 6 part 3; mock-up app26 and app29)
  bc_t: ["Bank and cash", "ធនាគារ និងសាច់ប្រាក់"],
  bc_sub: [
    "At each month end: match the bank book to the ABA statement, and count the cash. Month-end close checks both.",
    "នៅចុងខែនីមួយៗ៖ ផ្ទៀងសៀវភៅធនាគារជាមួយរបាយការណ៍ ABA ហើយរាប់សាច់ប្រាក់។ ការបិទចុងខែពិនិត្យទាំងពីរ។",
  ],
  bc_bank: ["Bank reconciliation", "ការផ្ទៀងផ្ទាត់ធនាគារ"],
  bc_cash: ["Cash count", "ការរាប់សាច់ប្រាក់"],
  bk_done: ["Matched", "ត្រូវគ្នា"],
  bk_done_by: ["Done by {0}, {1}", "ធ្វើដោយ {0}, {1}"],
  bk_stmt: ["ABA statement balance on {0}", "សមតុល្យរបាយការណ៍ ABA នៅ {0}"],
  bk_stmt_hr: [
    "Type the closing riel balance printed on the ABA riel account statement.",
    "វាយសមតុល្យរៀលចុងគ្រាដែលបោះពុម្ពលើរបាយការណ៍គណនីរៀល ABA។",
  ],
  bk_e_stmt_r: [
    "Type the statement balance in whole riel.",
    "សូមវាយសមតុល្យរបាយការណ៍ជារៀលគត់។",
  ],
  bk_worth: ["Value in dollars on {0}", "តម្លៃជាដុល្លារនៅ {0}"],
  bk_stmt_h: [
    "Type the closing balance printed on the ABA statement.",
    "វាយសមតុល្យចុងគ្រាដែលបោះពុម្ពលើរបាយការណ៍ ABA។",
  ],
  bk_in_book: [
    "In the book, not on the statement yet",
    "មាននៅសៀវភៅ មិនទាន់មានលើរបាយការណ៍",
  ],
  bk_in_stmt: [
    "On the statement, not in the book yet",
    "មានលើរបាយការណ៍ មិនទាន់មាននៅសៀវភៅ",
  ],
  bk_none: ["Nothing.", "គ្មាន។"],
  bk_sum: ["Do they match?", "តើត្រូវគ្នាទេ?"],
  bk_less_tr: [
    "Less money in the book, not on the statement yet",
    "ដកប្រាក់នៅសៀវភៅ មិនទាន់លើរបាយការណ៍",
  ],
  bk_adj: ["Book after these", "សៀវភៅក្រោយទាំងនេះ"],
  bk_diff: ["Difference", "ភាពខុសគ្នា"],
  bk_ok: ["Matches", "ត្រូវគ្នា"],
  bk_bad: ["Does not match", "មិនត្រូវគ្នា"],
  bk_ok_n: ["The book equals the statement.", "សៀវភៅស្មើរបាយការណ៍។"],
  bk_bad_n: [
    "Find the difference before you mark the month as matched.",
    "រកភាពខុសគ្នាមុនពេលសម្គាល់ខែថាត្រូវគ្នា។",
  ],
  bk_mark: ["Mark as matched", "សម្គាល់ថាត្រូវគ្នា"],
  bk_saved: ["Bank matched for {0}.", "ធនាគារត្រូវគ្នាសម្រាប់ {0}។"],
  cc_done: ["Counted", "បានរាប់"],
  cc_box: ["Cash", "សាច់ប្រាក់"],
  cc_book: ["Book on {0}", "សៀវភៅនៅ {0}"],
  cc_counted: ["Counted", "បានរាប់"],
  cc_khr_n: [
    "Count in riel. The app turns it into dollars at today's rate.",
    "រាប់ជារៀល។ កម្មវិធីប្ដូរជាដុល្លារតាមអត្រាថ្ងៃនេះ។",
  ],
  cc_usd_n: ["Count in dollars", "រាប់ជាដុល្លារ"],
  cc_about: ["About {0}", "ប្រហែល {0}"],
  cc_sub: [
    "Count the office cash and the petty cash at the end of {0}, then type what you counted.",
    "រាប់សាច់ប្រាក់ការិយាល័យ និងសាច់ប្រាក់រាយនៅចុង {0} រួចវាយចំនួនដែលបានរាប់។",
  ],
  cc_e_all: [
    "Type what you counted in every box.",
    "សូមវាយចំនួនដែលបានរាប់គ្រប់ប្រអប់។",
  ],
  cc_why: ["Reason for any difference", "មូលហេតុនៃភាពខុសគ្នា"],
  cc_why_h: [
    "Needed only when a count is different. The difference goes to 6180 Cash short or over.",
    "ត្រូវការតែពេលការរាប់ខុសគ្នា។ ភាពខុសគ្នាចូល 6180 សាច់ប្រាក់ខ្វះ ឬលើស។",
  ],
  cc_save: ["Save count", "រក្សាទុកការរាប់"],
  cc_saved: [
    "Cash count saved for {0}.",
    "បានរក្សាទុកការរាប់សាច់ប្រាក់សម្រាប់ {0}។",
  ],
  mm_t: ["Move money", "ផ្ទេរប្រាក់"],
  mm_from: ["From", "ពី"],
  mm_to: ["To", "ទៅ"],
  mm_riel: ["Riel amount", "ចំនួនរៀល"],
  mm_rate: ["Rate (riel for 1 dollar)", "អត្រា (រៀលក្នុង ១ ដុល្លារ)"],
  mm_rate_h: [
    "The rate you really got. Today's ABA rate is filled in.",
    "អត្រាដែលអ្នកទទួលបានពិត។ អត្រា ABA ថ្ងៃនេះបានបំពេញរួច។",
  ],
  mm_prev: [
    "You get {0}. The books hold this riel at {1}. {2}",
    "អ្នកទទួលបាន {0}។ សៀវភៅកាន់រៀលនេះនៅ {1}។ {2}",
  ],
  mm_gain: [
    "Exchange gain {0} goes to 4100.",
    "ចំណេញពីការប្ដូរប្រាក់ {0} ចូល ៤១០០។",
  ],
  mm_loss: [
    "Exchange loss {0} goes to 4100.",
    "ខាតពីការប្ដូរប្រាក់ {0} ចូល ៤១០០។",
  ],
  mm_n: [
    "For riel, type the riel amount and the rate. The app works out the gain or loss.",
    "សម្រាប់រៀល វាយចំនួនរៀល និងអត្រា។ កម្មវិធីគណនាចំណេញ ឬខាត។",
  ],
  mm_ok: ["Move money", "ផ្ទេរប្រាក់"],
  mm_done: ["Money moved. Entry {0}.", "បានផ្ទេរប្រាក់។ ធាតុ {0}។"],
  mm_e_same: ["Pick two different places.", "ជ្រើសកន្លែងពីរផ្សេងគ្នា។"],
  mm_e_riel: ["Type the riel amount and the rate.", "វាយចំនួនរៀល និងអត្រា។"],
  mm_e_bal: [
    "There is not that much money there.",
    "មិនមានប្រាក់ច្រើនដល់ម្ល៉េះទេ។",
  ],
  ow_t: ["Owner money", "ប្រាក់ម្ចាស់"],
  ow_dir: ["Which way", "ទិសដៅ"],
  ow_in: ["Money in", "ដាក់ប្រាក់ចូល"],
  ow_in_s: [
    "The Owner puts money into the business. 3000 Owner's capital.",
    "ម្ចាស់ដាក់ប្រាក់ចូលអាជីវកម្ម។ ៣០០០ ដើមទុនម្ចាស់។",
  ],
  ow_out: ["Money out", "ដកប្រាក់ចេញ"],
  ow_out_s: [
    "The Owner takes money for themselves. 3100 Owner's drawings.",
    "ម្ចាស់ដកប្រាក់សម្រាប់ខ្លួន។ ៣១០០ ការដកប្រាក់របស់ម្ចាស់។",
  ],
  ow_acc: ["Cash or bank", "សាច់ប្រាក់ ឬធនាគារ"],
  ow_note: ["Note", "កំណត់ចំណាំ"],
  ow_n: [
    "Only the Owner can do this. It is not income and not an expense.",
    "មានតែម្ចាស់ទេដែលធ្វើបាន។ វាមិនមែនជាចំណូល ឬចំណាយទេ។",
  ],
  ow_ok: ["Save", "រក្សាទុក"],
  ow_done_in: [
    "Owner money in {0}. Entry {1}.",
    "ម្ចាស់ដាក់ប្រាក់ចូល {0}។ ធាតុ {1}។",
  ],
  ow_done_out: [
    "Owner money out {0}. Entry {1}.",
    "ម្ចាស់ដកប្រាក់ចេញ {0}។ ធាតុ {1}។",
  ],
  pt_t: ["Top up petty cash", "បំពេញសាច់ប្រាក់រាយ"],
  pt_now: [
    "Petty cash float {0}. In petty cash now {1}. You can add up to {2}.",
    "ប្រាក់រាយកំណត់ {0}។ មានក្នុងប្រាក់រាយឥឡូវ {1}។ អាចបន្ថែមរហូតដល់ {2}។",
  ],
  pt_ok: ["Top up", "បំពេញ"],
  pt_done: [
    "Petty cash topped up {0}. Entry {1}.",
    "បានបំពេញសាច់ប្រាក់រាយ {0}។ ធាតុ {1}។",
  ],
  pt_e_max: [
    "That is more than the float allows, or more than there is to take.",
    "ច្រើនជាងប្រាក់រាយកំណត់ ឬច្រើនជាងប្រាក់ដែលមាន។",
  ],
  pt_card: ["Petty cash", "សាច់ប្រាក់រាយ"],
  pt_float: ["Float (Petty cash rule)", "ប្រាក់រាយកំណត់ (ច្បាប់សាច់ប្រាក់រាយ)"],
  pt_bal: ["In petty cash now", "មានក្នុងប្រាក់រាយឥឡូវ"],
  pt_gap: ["Can top up", "អាចបំពេញ"],
  pt_open: [
    "Bills not recorded yet: {0}, {1}",
    "វិក្កយបត្រមិនទាន់កត់ត្រា៖ {0} សរុប {1}",
  ],
  pt_open0: [
    "Every petty cash bill is recorded.",
    "វិក្កយបត្រប្រាក់រាយទាំងអស់បានកត់ត្រា។",
  ],
  pt_n: [
    "Top up only up to the float in the Petty cash business rule.",
    "បំពេញត្រឹមប្រាក់រាយកំណត់ក្នុងច្បាប់អាជីវកម្មសាច់ប្រាក់រាយ។",
  ],
  kh_t: ["Riel cash", "សាច់ប្រាក់រៀល"],
  kh_bt: ["Riel in the bank", "រៀលក្នុងធនាគារ"],
  kh_bb: ["Value in the books ({0})", "តម្លៃក្នុងសៀវភៅ ({0})"],
  kh_bn: [
    "On the last day of each month the app values the riel in the bank at the month-end rate. The difference goes to 4100.",
    "នៅថ្ងៃចុងខែ កម្មវិធីវាយតម្លៃរៀលក្នុងធនាគារតាមអត្រាចុងខែ។ ភាពខុសគ្នាចូល ៤១០០។",
  ],
  kh_q: ["Riel held", "រៀលដែលកាន់"],
  kh_b: ["Value in the books (1011)", "តម្លៃក្នុងសៀវភៅ (១០១១)"],
  kh_last: ["Last month-end value", "តម្លៃចុងខែចុងក្រោយ"],
  kh_n: [
    "On the last day of each month the app values riel cash at the month-end rate. The difference goes to 4100.",
    "នៅថ្ងៃចុងខែ កម្មវិធីវាយតម្លៃសាច់ប្រាក់រៀលតាមអត្រាចុងខែ។ ភាពខុសគ្នាចូល ៤១០០។",
  ],
  br_e_reason: ["Say why.", "សូមប្រាប់មូលហេតុ។"],
  bk_book: ["Bank book ({1}) on {0}", "សៀវភៅធនាគារ ({1}) នៅ {0}"],
  // new
  bk_tick: [
    "Tick each line that is not on the ABA statement yet.",
    "គូសបន្ទាត់នីមួយៗដែលមិនទាន់មានលើរបាយការណ៍ ABA។",
  ],
  // new
  bk_not_yet: ["Not on the statement yet", "មិនទាន់មានលើរបាយការណ៍"],
  // new
  bk_fee_how: [
    "A bank fee or interest on the statement: record it in Expenses, paid from {0}. Then come back here.",
    "ថ្លៃធនាគារ ឬការប្រាក់លើរបាយការណ៍៖ កត់ត្រាវានៅក្នុងចំណាយ បង់ពី {0}។ បន្ទាប់មកត្រឡប់មកទីនេះវិញ។",
  ],
  // new
  bk_go_x: ["Open Expenses", "បើកចំណាយ"],
  // new
  bk_e_stmt: ["Type the statement balance.", "សូមវាយសមតុល្យរបាយការណ៍។"],
  // new
  mm_riel_in: ["Riel received", "រៀលដែលទទួលបាន"],
  // new
  mm_riel_in_h: [
    "The riel counted into riel cash. The books hold it at the dollar amount until the month end.",
    "រៀលដែលរាប់ចូលសាច់ប្រាក់រៀល។ សៀវភៅកាន់វាតាមចំនួនដុល្លាររហូតដល់ចុងខែ។",
  ],
  // new
  cc_e_rate: [
    "There is no riel rate for today, so riel cannot be counted. Ask the Owner to set it in Settings.",
    "មិនមានអត្រារៀលសម្រាប់ថ្ងៃនេះ ដូច្នេះមិនអាចរាប់រៀលបានទេ។ សូមស្នើម្ចាស់ឱ្យកំណត់វានៅក្នុងការកំណត់។",
  ],
  // new
  bc_no_month: [
    "No month has ended since the ledger started.",
    "មិនទាន់មានខែណាបញ្ចប់ចាប់តាំងពីសៀវភៅបញ្ជីចាប់ផ្ដើម។",
  ],
  // new
  bc_no_bank: [
    "There is no bank account in the chart of accounts.",
    "មិនមានគណនីធនាគារក្នុងតារាងគណនីទេ។",
  ],
  // new
  bc_closed: ["This month is closed.", "ខែនេះបានបិទ។"],
  // Month-end close (step 6 part 4; mock-up app22 and app26)
  gl_c_t: ["Month-end close", "ការបិទចុងខែ"],
  gl_c_closed: ["Closed", "បានបិទ"],
  gl_c_open: ["Open", "បើក"],
  gl_c_by: ["Closed by {0}, {1}", "បិទដោយ {0}, {1}"],
  gl_c_sub: [
    "When a month is closed, nothing can be dated in it. A later fix goes into the open month, linked to the first record.",
    "ពេលខែត្រូវបានបិទ គ្មានអ្វីអាចដាក់កាលបរិច្ឆេទក្នុងខែនោះទេ។ ការកែក្រោយចូលខែបើក ភ្ជាប់ទៅកំណត់ត្រាដំបូង។",
  ],
  gl_c_btn: ["Close month", "បិទខែ"],
  gl_c_done: ["{0} closed.", "បានបិទ {0}។"],
  br_by: ["Recorded by", "កត់ត្រាដោយ"],
  gl_src: ["From", "ពី"],
  cl_head: [
    "The app checks each line itself. A month can be closed only when every line is green.",
    "កម្មវិធីពិនិត្យបន្ទាត់នីមួយៗដោយខ្លួនឯង។ អាចបិទខែបានតែពេលគ្រប់បន្ទាត់ពណ៌បៃតង។",
  ],
  cl_next: ["Close {0}", "បិទ {0}"],
  cl_sub: [
    "Checked now, each time you open this page.",
    "ពិនិត្យឥឡូវ រាល់ពេលអ្នកបើកទំព័រនេះ។",
  ],
  cl_ok: ["Done", "រួចរាល់"],
  cl_bad: ["Not done", "មិនទាន់រួច"],
  cl_bad_n: ["{0} to fix", "{0} ត្រូវកែ"],
  cl_all_ok: ["Ready to close", "រួចរាល់ដើម្បីបិទ"],
  cl_fix: ["Open", "បើក"],
  cl_books: ["Books check", "ការត្រួតពិនិត្យសៀវភៅ"],
  cl_books_d: [
    "Every record has its entry, every entry is balanced, Customer debt equals the unpaid Invoices.",
    "កំណត់ត្រានីមួយៗមានធាតុ ធាតុនីមួយៗមានតុល្យភាព បំណុលអតិថិជនស្មើវិក្កយបត្រមិនទាន់បង់។",
  ],
  cl_wait: ["No request waiting", "គ្មានសំណើរង់ចាំ"],
  cl_wait_n: [
    "{0} Expense requests or adjusting entries dated in the month still wait for approval.",
    "សំណើចំណាយ ឬធាតុកែតម្រូវ {0} ក្នុងខែនៅរង់ចាំការអនុម័ត។",
  ],
  cl_wait_0: ["Nothing waits for approval.", "គ្មានអ្វីរង់ចាំការអនុម័ត។"],
  cl_late: ["No late report or advance", "គ្មានរបាយការណ៍ ឬប្រាក់បុរេប្រទានយឺត"],
  cl_late_n: [
    "{0} staff advances are past the report days.",
    "ប្រាក់បុរេប្រទាន {0} ហួសថ្ងៃរាយការណ៍។",
  ],
  cl_late_0: ["No advance is late.", "គ្មានប្រាក់បុរេប្រទានយឺត។"],
  cl_bank: ["Bank matched", "ធនាគារត្រូវគ្នា"],
  cl_bank_n: [
    "Match the bank book to the ABA statement of {0}.",
    "ផ្ទៀងសៀវភៅធនាគារជាមួយរបាយការណ៍ ABA នៃ {0}។",
  ],
  cl_cash: ["Cash counted", "បានរាប់សាច់ប្រាក់"],
  cl_cash_n: [
    "Count the office cash and petty cash of {0}.",
    "រាប់សាច់ប្រាក់ការិយាល័យ និងសាច់ប្រាក់រាយនៃ {0}។",
  ],
  cl_dep: ["Depreciation done", "រំលោះរួចរាល់"],
  cl_dep_n: [
    "The depreciation entry for the month is missing.",
    "ខ្វះធាតុរំលោះសម្រាប់ខែ។",
  ],
  cl_dep_0: ["No fixed asset to depreciate.", "គ្មានទ្រព្យសកម្មត្រូវរំលោះ។"],
  cl_btn: ["Close {0}", "បិទ {0}"],
  cl_btn_n: ["Fix the red lines first.", "សូមកែបន្ទាត់ពណ៌ក្រហមជាមុនសិន។"],
  cl_owner: ["Only the Owner closes a month.", "មានតែម្ចាស់ទេដែលបិទខែ។"],
  cl_none: [
    "No month is ready to close. {0} ends on {1}.",
    "គ្មានខែណារួចរាល់ដើម្បីបិទ។ {0} បញ្ចប់នៅ {1}។",
  ],
  cl_months: ["Months", "ខែ"],
  cl_now: ["To close now", "ត្រូវបិទឥឡូវ"],
  cl_conf: [
    "Every check is green. After closing, nothing can be dated in {0}. A later fix goes into the open month.",
    "គ្រប់ការពិនិត្យពណ៌បៃតង។ ក្រោយបិទ គ្មានអ្វីអាចដាក់កាលបរិច្ឆេទក្នុង {0} ទៀតទេ។ ការកែក្រោយចូលខែដែលបើក។",
  ],
  ye_t: ["Year-end close", "បិទចុងឆ្នាំ"],
  ye_sub: [
    "After December is closed, the Owner closes the year. The year's profit moves to 3900 Profit kept from past years.",
    "ក្រោយបិទខែធ្នូ ម្ចាស់បិទឆ្នាំ។ ចំណេញនៃឆ្នាំផ្ទេរទៅ 3900 ចំណេញរក្សាទុកពីឆ្នាំមុន។",
  ],
  ye_year: ["Year", "ឆ្នាំ"],
  ye_profit: ["Profit moved to 3900", "ចំណេញផ្ទេរទៅ 3900"],
  ye_closed: ["Closed", "បានបិទ"],
  ye_btn: ["Close year", "បិទឆ្នាំ"],
  ye_wait: [
    "You can close {0} after December {0} is closed.",
    "អ្នកអាចបិទ {0} ក្រោយបិទខែធ្នូ {0}។",
  ],
  ye_conf: [
    "The profit of {0}, {1}, moves to 3900. Income and expense accounts start the new year at zero.",
    "ចំណេញនៃ {0} គឺ {1} ផ្ទេរទៅ 3900។ គណនីចំណូល និងចំណាយចាប់ផ្ដើមឆ្នាំថ្មីពីសូន្យ។",
  ],
  ye_done: ["Year {0} closed. Entry {1}.", "បានបិទឆ្នាំ {0}។ ធាតុ {1}។"],
  cl_pay: ["Payroll approved", "បញ្ជីប្រាក់ខែបានអនុម័ត"],
  cl_pay_none: [
    "No payroll for this month.",
    "គ្មានបញ្ជីប្រាក់ខែសម្រាប់ខែនេះ។",
  ],
  cl_fx: ["Riel valued at month-end rate", "រៀលវាយតម្លៃតាមអត្រាចុងខែ"],
  // Riel at month end (owner 05/11/2026)
  cl_rt: ["Riel at month end", "រៀលនៅចុងខែ"],
  cl_rs: [
    "Each riel account is valued at the app's rate on the month's last day. The difference goes to 4100.",
    "គណនីរៀលនីមួយៗត្រូវបានវាយតម្លៃតាមអត្រារបស់កម្មវិធីនៅថ្ងៃចុងខែ។ ភាពខុសគ្នាចូល ៤១០០។",
  ],
  cl_rheld: ["Riel held", "រៀលដែលមាន"],
  cl_rrate: ["Rate", "អត្រា"],
  cl_rbefore: ["Value before", "តម្លៃមុន"],
  cl_rafter: ["Value after", "តម្លៃក្រោយ"],
  cl_rgain: ["Gain or loss", "ចំណេញ ឬខាត"],
  cl_fx_0: [
    "No change: the riel value is the same.",
    "គ្មានការប្ដូរ៖ តម្លៃរៀលដូចដើម។",
  ],
  cl_fx_n: ["The app makes this entry on {0}.", "កម្មវិធីធ្វើធាតុនេះនៅ {0}។"],
  // new
  cl_done_n: ["Done.", "រួចរាល់។"],
  // new
  cl_not_closed: [
    "{0} is not closed yet. Fix the red lines, then try again.",
    "{0} មិនទាន់បានបិទទេ។ កែបន្ទាត់ពណ៌ក្រហម រួចសាកម្តងទៀត។",
  ],
  // new
  ye_conf_n: [
    "The year's profit moves to 3900. Income and expense accounts start the new year at zero.",
    "ចំណេញនៃឆ្នាំផ្ទេរទៅ 3900។ គណនីចំណូល និងចំណាយចាប់ផ្ដើមឆ្នាំថ្មីពីសូន្យ។",
  ],
  // Fixed assets (step 6 part 4; mock-up v76 vFassets).
  fa_t: ["Fixed assets", "ទ្រព្យសកម្មរយៈពេលវែង"],
  fa_sub: [
    "Equipment and building items of the asset limit or more. The app makes the depreciation entry at the end of each month.",
    "ឧបករណ៍ និងរបស់ក្នុងអគារដែលមានតម្លៃចាប់ពីកម្រិតទ្រព្យសកម្មឡើងទៅ។ កម្មវិធីបង្កើតធាតុរំលោះនៅចុងខែនីមួយៗ។",
  ],
  fa_new: ["Add fixed asset", "បន្ថែមទ្រព្យសកម្មរយៈពេលវែង"],
  fa_list: ["Register", "បញ្ជី"],
  fa_item: ["Item", "របស់"],
  fa_cost: ["Cost", "ថ្លៃដើម"],
  fa_life: ["Useful life (years)", "អាយុប្រើប្រាស់ (ឆ្នាំ)"],
  fa_years: ["{0} years", "{0} ឆ្នាំ"],
  fa_mon: ["Each month", "ប្រចាំខែ"],
  fa_sofar: ["Depreciation so far", "រំលោះរហូតមកដល់ពេលនេះ"],
  fa_now: ["Value now", "តម្លៃបច្ចុប្បន្ន"],
  fa_date: ["Date bought", "កាលបរិច្ឆេទទិញ"],
  fa_check: [
    "Depreciation so far equals Accumulated depreciation (1590): {0}.",
    "រំលោះរហូតមកដល់ពេលនេះ ស្មើរំលោះបង្គរ (1590)៖ {0}។",
  ],
  fa_note: [
    "Business rule: items of {0} or more go here. Depreciation is the same each month, from the month after the item is bought.",
    "ច្បាប់អាជីវកម្ម៖ របស់ដែលមានតម្លៃ {0} ឬច្រើនជាងនេះ ដាក់ទីនេះ។ រំលោះស្មើគ្នាជារៀងរាល់ខែ ចាប់ពីខែបន្ទាប់ពីទិញ។",
  ],
  fa_last: [
    "Last depreciation entry: {0}, {1}.",
    "ធាតុរំលោះចុងក្រោយ៖ {0}, {1}។",
  ],
  fa_e_name: ["Type the item name.", "សូមវាយឈ្មោះរបស់។"],
  fa_e_life: [
    "Type the number of years, 1 to 50.",
    "សូមវាយចំនួនឆ្នាំ ពី ១ ដល់ ៥០។",
  ],
  fa_e_small: [
    "Below {0}: record it on Expenses instead.",
    "តិចជាង {0}៖ សូមកត់ត្រានៅចំណាយជំនួសវិញ។",
  ],
  fa_new_n: [
    "Items of {0} or more only.",
    "តែរបស់ដែលមានតម្លៃ {0} ឬច្រើនជាងនេះ។",
  ],
  fa_new_m: [
    "Depreciation: {0} each month, first on {1}.",
    "រំលោះ៖ {0} ប្រចាំខែ លើកដំបូងនៅ {1}។",
  ],
  fa_saved: [
    "Fixed asset {0} added. Entry {1}.",
    "បានបន្ថែមទ្រព្យសកម្ម {0}។ ធាតុ {1}។",
  ],
  // new: the reason kept when the years typed differ from Business rules.
  fa_life_why: [
    "Years set when the item was added.",
    "ចំនួនឆ្នាំកំណត់នៅពេលបន្ថែមរបស់។",
  ],
  // new
  fa_none: ["No fixed assets yet.", "មិនទាន់មានទ្រព្យសកម្មរយៈពេលវែងទេ។"],
  // new
  fa_land: ["Not depreciated", "មិនរំលោះ"],
  // Budget (step 6 part 4; mock-up v76 vBudget).
  bu_t: ["Budget", "ថវិកា"],
  bu_sub: [
    "The Accountant prepares the budget by month for the year. The Owner approves it. Budget vs actual is under Financial statements.",
    "គណនេយ្យកររៀបចំថវិកាតាមខែសម្រាប់មួយឆ្នាំ។ ម្ចាស់អនុម័ត។ ថវិកាធៀបនឹងជាក់ស្ដែង នៅក្នុងរបាយការណ៍ហិរញ្ញវត្ថុ។",
  ],
  bu_year: ["Year", "ឆ្នាំ"],
  bu_for: ["Budget {0}", "ថវិកា {0}"],
  bu_st_OK: ["Approved", "បានអនុម័ត"],
  bu_st_WAIT: ["Waits for the Owner", "រង់ចាំម្ចាស់"],
  bu_st_DRAFT: ["Draft", "សេចក្ដីព្រាង"],
  bu_send: ["Send to the Owner", "ផ្ញើទៅម្ចាស់"],
  bu_ok: ["Approve budget", "អនុម័តថវិកា"],
  bu_back: ["Send back", "ផ្ញើត្រឡប់"],
  bu_ti: ["Total income", "ចំណូលសរុប"],
  bu_tx: ["Total expenses", "ចំណាយសរុប"],
  bu_pr: ["Profit", "ចំណេញ"],
  bu_who: ["Prepared by {0}, {1}", "រៀបចំដោយ {0}, {1}"],
  bu_who_ok: [
    "Prepared by {0}, {1}. Approved by {2}, {3}.",
    "រៀបចំដោយ {0}, {1}។ អនុម័តដោយ {2}, {3}។",
  ],
  bu_self: [
    "You sent this budget. Someone else must approve it.",
    "អ្នកបានផ្ញើថវិកានេះ។ អ្នកផ្សេងត្រូវអនុម័តវា។",
  ],
  bu_wait: ["Waits for the Owner to approve.", "រង់ចាំម្ចាស់អនុម័ត។"],
  bu_locked: [
    "An approved budget is locked.",
    "ថវិកាដែលបានអនុម័តត្រូវបានចាក់សោ។",
  ],
  bu_edit_n: [
    "Tap an account to type its amounts for each month.",
    "ចុចលើគណនី ដើម្បីវាយចំនួនសម្រាប់ខែនីមួយៗ។",
  ],
  bu_backed: ["Sent back by {0}: {1}", "ផ្ញើត្រឡប់ដោយ {0}៖ {1}"],
  bu_edit_t: ["Budget: {0}", "ថវិកា៖ {0}"],
  bu_same: ["Same amount every month", "ចំនួនដូចគ្នារៀងរាល់ខែ"],
  bu_fill: ["Fill all months", "បំពេញគ្រប់ខែ"],
  bu_saved: ["Budget amounts saved.", "បានរក្សាទុកចំនួនថវិកា។"],
  bu_sent: ["Budget {0} sent to the Owner.", "បានផ្ញើថវិកា {0} ទៅម្ចាស់។"],
  bu_done: ["Budget {0} approved.", "បានអនុម័តថវិកា {0}។"],
  bu_backed_t: ["Budget {0} sent back.", "បានផ្ញើថវិកា {0} ត្រឡប់។"],
  // new: the Owner's own budget is approved at once (PR-GL-054).
  bu_own_n: [
    "Your own budget is approved at once. Add a note for the record.",
    "ថវិកាផ្ទាល់ខ្លួនរបស់អ្នកត្រូវបានអនុម័តភ្លាមៗ។ សូមបន្ថែមកំណត់ចំណាំសម្រាប់កំណត់ត្រា។",
  ],
  // new
  bu_e_note: ["Add a note.", "សូមបន្ថែមកំណត់ចំណាំ។"],
  // new
  bu_e_amt: ["Type an amount of 0 or more.", "សូមវាយចំនួនចាប់ពី ០ ឡើងទៅ។"],
  // new
  bu_no_year: [
    "The ledger has no year yet.",
    "សៀវភៅបញ្ជីមិនទាន់មានឆ្នាំនៅឡើយទេ។",
  ],
  // new
  bu_closed: ["The year {0} is closed.", "ឆ្នាំ {0} ត្រូវបានបិទ។"],
  // Void an Expense, Reverse a bill payment (mock-up v77, round 34).
  x39_act: ["Action", "សកម្មភាព"],
  x39_void: ["Void", "ទុកជាមោឃៈ"],
  x39_void_t: ["Void expense {0}", "ទុកចំណាយ {0} ជាមោឃៈ"],
  x39_void_b: ["{0} · {1} · paid from {2}", "{0} · {1} · បង់ពី {2}"],
  x39_void_n: [
    "An expense is never edited. Void makes a reversing entry today and keeps the expense in the list as Void. If it was wrong, record it again.",
    "ចំណាយមិនដែលកែទេ។ ការទុកជាមោឃៈធ្វើធាតុបញ្ច្រាសនៅថ្ងៃនេះ ហើយរក្សាចំណាយក្នុងបញ្ជីជាមោឃៈ។ បើវាខុស កត់ត្រាម្ដងទៀត។",
  ],
  x39_void_bill: [
    "It was to pay later, so its supplier bill {0} is voided with it.",
    "វាត្រូវបង់ពេលក្រោយ ដូច្នេះវិក្កយបត្រអ្នកផ្គត់ផ្គង់ {0} ក៏ត្រូវទុកជាមោឃៈជាមួយ។",
  ],
  x39_void_done: [
    "{0} voided. Reversing entry {1}.",
    "{0} បានទុកជាមោឃៈ។ ធាតុបញ្ច្រាស {1}។",
  ],
  x39_void_s: ["Voided by {0} · {1} · {2}", "ទុកជាមោឃៈដោយ {0} · {1} · {2}"],
  x39_paid_first: [
    "Reverse the payments of bill {0} first",
    "បញ្ច្រាសការបង់របស់វិក្កយបត្រ {0} ជាមុនសិន",
  ],
  sb39_paid: ["Paid {0} on {1} from {2}", "បានបង់ {0} នៅ {1} ពី {2}"],
  sb39_rev: ["Reverse payment", "បញ្ច្រាសការបង់"],
  sb39_rev_t: ["Reverse a payment on {0}", "បញ្ច្រាសការបង់លើ {0}"],
  sb39_rev_b: [
    "{0} paid on {1} from {2} to {3}.",
    "{0} បានបង់នៅ {1} ពី {2} ទៅ {3}។",
  ],
  sb39_rev_n: [
    "Use this when the payment was made by mistake or was wrong. The bill owes this money again; pay it again if needed.",
    "ប្រើពេលការបង់ធ្វើដោយច្រឡំ ឬខុស។ វិក្កយបត្រជំពាក់ប្រាក់នេះម្ដងទៀត; បង់ម្ដងទៀតបើត្រូវការ។",
  ],
  sb39_rev_done: [
    "Payment on {0} reversed. Entry {1}.",
    "ការបង់លើ {0} បានបញ្ច្រាស។ ធាតុ {1}។",
  ],
  sb39_reved: ["Reversed by {0} · {1} · {2}", "បញ្ច្រាសដោយ {0} · {1} · {2}"],
  ent39: ["The entry:", "ធាតុ៖"],
  wo_dr: ["debit {0}", "ឥណពន្ធ {0}"],
  wo_cr: ["credit {0}", "ឥណទាន {0}"],
  // Opening balances (mock-up lopen, DESIGN.md round 22, phase 6 plan L3).
  ob_t: ["Opening balances", "សមតុល្យដើម"],
  ob_sub: [
    "What the business had and owed on the day the books start.",
    "អ្វីដែលអាជីវកម្មមាន និងជំពាក់ នៅថ្ងៃចាប់ផ្ដើមសៀវភៅ។",
  ],
  ob_on: ["Books start on {0}", "សៀវភៅចាប់ផ្ដើមនៅ {0}"],
  ob_locked: ["Locked", "បានចាក់សោ"],
  ob_draft: ["Not posted yet", "មិនទាន់ប្រកាស"],
  ob_note: [
    "Opening balances are locked once posted. A later fix goes in as an adjusting entry.",
    "សមតុល្យដើមចាក់សោពេលបានប្រកាស។ ការកែក្រោយចូលជាធាតុកែតម្រូវ។",
  ],
  ob_none: [
    "The books have not started yet. They start on 1 January of the first year, with what the business had and owed the day before.",
    "សៀវភៅមិនទាន់ចាប់ផ្ដើមទេ។ វាចាប់ផ្ដើមថ្ងៃទី១ ខែមករា នៃឆ្នាំដំបូង ជាមួយអ្វីដែលអាជីវកម្មមាន និងជំពាក់ នៅថ្ងៃមុន។",
  ],
  ob_start: ["Start the books", "ចាប់ផ្ដើមសៀវភៅ"],
  ob_year: ["First year", "ឆ្នាំដំបូង"],
  ob_year_n: [
    "The books start on 01/01/{0}. Opening balances are as at 31/12/{1}.",
    "សៀវភៅចាប់ផ្ដើមនៅ 01/01/{0}។ សមតុល្យដើមគិតត្រឹម 31/12/{1}។",
  ],
  ob_e_year: ["Type a year such as 2027.", "វាយឆ្នាំ ដូចជា 2027។"],
  ob_started: [
    "The books start on {0}. Type the opening balances next.",
    "សៀវភៅចាប់ផ្ដើមនៅ {0}។ បន្ទាប់មក វាយបញ្ចូលសមតុល្យដើម។",
  ],
  ob_typed_t: ["Accounts you type", "គណនីដែលអ្នកវាយបញ្ចូល"],
  ob_typed_s: [
    "Cash, bank, equipment, loans, the Owner's capital and every other account the app does not work out.",
    "សាច់ប្រាក់ ធនាគារ ឧបករណ៍ ប្រាក់កម្ចី ដើមទុនម្ចាស់ និងគណនីផ្សេងទៀតដែលកម្មវិធីមិនគណនា។",
  ],
  ob_typed_none: ["Nothing typed yet.", "មិនទាន់វាយបញ្ចូលអ្វីទេ។"],
  ob_worked_t: ["Worked out by the app", "កម្មវិធីគណនា"],
  ob_worked_s: [
    "Customer debt, Deposits, Customer Credit, money not used yet and Rent billed in advance come from the app's own lists.",
    "បំណុលអតិថិជន ប្រាក់កក់ ឥណទានអតិថិជន ប្រាក់មិនទាន់ប្រើ និងថ្លៃឈ្នួលចេញវិក្កយបត្រមុន មកពីបញ្ជីរបស់កម្មវិធីផ្ទាល់។",
  ],
  ob_worked_none: [
    "Nothing to bring from the app's lists.",
    "គ្មានអ្វីត្រូវយកពីបញ្ជីរបស់កម្មវិធីទេ។",
  ],
  ob_type: ["Type the opening balances", "វាយបញ្ចូលសមតុល្យដើម"],
  ob_add: ["Add account", "បន្ថែមគណនី"],
  ob_remove: ["Remove {0}", "ដកចេញ {0}"],
  ob_pick: ["Choose an account", "ជ្រើសរើសគណនី"],
  ob_e_acct: ["Choose an account.", "សូមជ្រើសរើសគណនី។"],
  ob_e_twice: ["Each account goes in once.", "គណនីនីមួយៗចូលតែម្ដង។"],
  ob_e_one: [
    "Type a debit or a credit, more than zero, not both.",
    "វាយឥណពន្ធ ឬឥណទាន ច្រើនជាងសូន្យ មិនមែនទាំងពីរទេ។",
  ],
  ob_e_lines: ["Add at least one account.", "បន្ថែមយ៉ាងហោចណាស់មួយគណនី។"],
  ob_saved: ["Opening balances saved.", "បានរក្សាទុកសមតុល្យដើម។"],
  ob_off: [
    "Off by {0}. Put the difference on an equity account such as 3000 Owner's capital.",
    "ខុសគ្នា {0}។ សូមដាក់ភាពខុសគ្នាលើគណនីមូលធន ដូចជា 3000 ដើមទុនម្ចាស់។",
  ],
  ob_nc: [
    "{0} records wait in Needs check. Clear that list before you post.",
    "កំណត់ត្រា {0} កំពុងរង់ចាំក្នុង ត្រូវពិនិត្យ។ សូមដោះស្រាយបញ្ជីនោះ មុនពេលប្រកាស។",
  ],
  ob_empty: [
    "Type the opening balances first. Post opens when Debit and Credit are equal.",
    "សូមវាយបញ្ចូលសមតុល្យដើមជាមុនសិន។ ប៊ូតុងប្រកាសបើកពេលឥណពន្ធ និងឥណទានស្មើគ្នា។",
  ],
  ob_post: ["Post opening balances", "ប្រកាសសមតុល្យដើម"],
  ob_post_n: [
    "This posts one entry dated {0}. After that the opening balances are locked; a later fix goes in as an adjusting entry.",
    "នេះប្រកាសធាតុមួយ ចុះថ្ងៃ {0}។ បន្ទាប់មក សមតុល្យដើមត្រូវចាក់សោ ការកែក្រោយចូលជាធាតុកែតម្រូវ។",
  ],
  ob_posted: ["Opening balances posted.", "បានប្រកាសសមតុល្យដើម។"],
  ob_entry: ["Entry {0}", "ធាតុ {0}"],
  ob_by: ["Posted by {0} · {1}", "ប្រកាសដោយ {0} · {1}"],
  ob_owner: [
    "Only the Owner starts the books and types the opening balances.",
    "មានតែម្ចាស់ទេ ដែលចាប់ផ្ដើមសៀវភៅ និងវាយបញ្ចូលសមតុល្យដើម។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type LedgerTextKey = keyof typeof TEXT;

export function lt(
  language: Language,
  key: LedgerTextKey,
  ...values: string[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return values.reduce(
    (out, value, index) => out.split(`{${String(index)}}`).join(value),
    text,
  );
}

export function hasLedgerText(key: string): key is LedgerTextKey {
  return Object.prototype.hasOwnProperty.call(TEXT, key);
}

export function typeName(language: Language, type: AccountType): string {
  return lt(language, `t_${type}`);
}

/** "2027-01-01" → "January 2027" in the chosen language. */
const MONTHS = [
  ["January", "មករា"],
  ["February", "កុម្ភៈ"],
  ["March", "មីនា"],
  ["April", "មេសា"],
  ["May", "ឧសភា"],
  ["June", "មិថុនា"],
  ["July", "កក្កដា"],
  ["August", "សីហា"],
  ["September", "កញ្ញា"],
  ["October", "តុលា"],
  ["November", "វិច្ឆិកា"],
  ["December", "ធ្នូ"],
] as const;

export function monthLabel(language: Language, day: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(day);
  if (match === null) return day;
  const [, year = "", month = "1"] = match;
  const names = MONTHS[Number(month) - 1];
  return names === undefined
    ? day
    : `${names[language === "en" ? 0 : 1]} ${year}`;
}

/** Month 1 to 12 short: "Jan" in English, the full name in Khmer (as in mock-up v76). */
export function monthShort(language: Language, month: number): string {
  const names = MONTHS[month - 1];
  if (names === undefined) return String(month);
  return language === "en" ? names[0].slice(0, 3) : names[1];
}

/** Month 1 to 12 in full. */
export function monthName(language: Language, month: number): string {
  const names = MONTHS[month - 1];
  return names === undefined ? String(month) : names[language === "en" ? 0 : 1];
}
