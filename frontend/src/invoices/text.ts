// V1-058 R5: the words of the Invoices screens in English and Khmer, from the owner's mock-up
// (i18n.js). Khmer needs the native check before the app is used. Lines marked "new" are not
// in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  inv_sub: ["All Invoices", "វិក្កយបត្រទាំងអស់"],
  inv_sub_m: ["Invoices due in {0}", "វិក្កយបត្រដល់កំណត់ក្នុងខែ{0}"],
  // new
  loading: ["Loading the Invoices…", "កំពុងផ្ទុកវិក្កយបត្រ…"],
  // new
  failed: [
    "The Invoices could not be read just now. Check the connection and try again.",
    "មិនអាចអានវិក្កយបត្របានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  pm_period: ["Month", "ខែ"],
  f_all: ["All", "ទាំងអស់"],
  pc_month: ["This month", "ខែនេះ"],
  pc_last: ["Last month", "ខែមុន"],
  pm_pick: ["Pick a month", "ជ្រើសខែ"],
  type_all: ["All types", "គ្រប់ប្រភេទ"],
  RENT: ["Rent", "ថ្លៃឈ្នួល"],
  UTILITIES: ["Utilities", "ថ្លៃទឹកភ្លើង"],
  // new
  SERVICE_CHARGES: ["Services", "សេវា"],
  MISCELLANEOUS_CHARGES: ["Miscellaneous", "ផ្សេងៗ"],
  DAMAGE_CHARGES: ["Damage", "ការខូចខាត"],
  ic_total: ["Total Invoice amount", "ចំនួនវិក្កយបត្រសរុប"],
  ic_total_s: ["Issued Invoices", "វិក្កយបត្រដែលបានចេញ"],
  ic_unpaid: ["Total unpaid", "មិនទាន់បង់សរុប"],
  ic_unpaid_s: ["Still owed, overdue included", "នៅជំពាក់ រួមទាំងហួសកំណត់"],
  ic_over: ["Total overdue", "ហួសកំណត់សរុប"],
  ic_over_s: ["Past the due date", "ហួសថ្ងៃកំណត់បង់"],
  ic_paid: ["Total paid", "បានបង់សរុប"],
  ic_paid_s: ["Part payments included", "រួមទាំងការបង់ខ្លះ"],
  ic_n1: ["1 Invoice", "វិក្កយបត្រ 1"],
  ic_n: ["{0} Invoices", "វិក្កយបត្រ {0}"],
  ic_addup: [
    "Paid {0} + unpaid {1} = {2}.",
    "បានបង់ {0} + មិនទាន់បង់ {1} = {2}។",
  ],
  ic_addup_late: [
    "Overdue {0} is part of unpaid.",
    "ហួសកំណត់ {0} ជាផ្នែកនៃមិនទាន់បង់។",
  ],
  ic_drafts: [
    "{0} Drafts are not counted until they are issued.",
    "សេចក្តីព្រាង {0} មិនទាន់រាប់ រហូតដល់ចេញ។",
  ],
  ic_drafts1: [
    "1 Draft is not counted until it is issued.",
    "សេចក្តីព្រាង 1 មិនទាន់រាប់ រហូតដល់ចេញ។",
  ],
  // new
  ic_voids: ["{0} void, not counted", "ទុកជាមោឃៈ {0} មិនរាប់"],
  ic_showing: ["Showing: {0}.", "កំពុងបង្ហាញ៖ {0}។"],
  pc_clear: ["Show all", "បង្ហាញទាំងអស់"],
  for_who: ["Showing only {0}", "បង្ហាញតែ {0}"],
  clear_filter: ["Show everyone", "បង្ហាញទាំងអស់"],
  col_no: ["Invoice No.", "លេខវិក្កយបត្រ"],
  col_cust: ["Customer", "អតិថិជន"],
  col_type: ["Type", "ប្រភេទ"],
  col_due: ["Due date", "ថ្ងៃកំណត់បង់"],
  col_amount: ["Amount", "ចំនួនទឹកប្រាក់"],
  col_balance: ["Balance", "សមតុល្យ"],
  col_status: ["Status", "ស្ថានភាព"],
  col_unit: ["Unit", "បន្ទប់"],
  ni_draft_no: ["Draft", "សេចក្តីព្រាង"],
  ni_due_later: ["Set when issued", "កំណត់ពេលចេញ"],
  none_found: [
    "No Invoices match these filters.",
    "គ្មានវិក្កយបត្រត្រូវនឹងតម្រងនេះទេ។",
  ],
  st_draft: ["Draft", "សេចក្តីព្រាង"],
  st_paid: ["Paid", "បានបង់"],
  st_part: ["Part paid", "បង់បានខ្លះ"],
  st_unpaid: ["Not paid", "មិនទាន់បង់"],
  st_overdue: ["Overdue", "ហួសកំណត់"],
  // new
  st_void: ["Void", "ទុកជាមោឃៈ"],
  // new
  unknown_customer: ["Customer not shown", "មិនបង្ហាញអតិថិជន"],
  back: ["Back to Invoices", "ត្រឡប់ទៅវិក្កយបត្រ"],
  // new
  not_found: [
    "This Invoice was not found, or you may not see it.",
    "រកមិនឃើញវិក្កយបត្រនេះ ឬអ្នកមិនអាចមើលវាបានទេ។",
  ],
  // new
  loading_one: ["Loading the Invoice…", "កំពុងផ្ទុកវិក្កយបត្រ…"],
  act_pay: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  // changed: the mock-up's late charge sentence waits for the late-payment card
  late_banner: [
    "This Invoice is overdue. It became overdue on {0}, the day after its Due Date.",
    "វិក្កយបត្រនេះហួសកំណត់។ វាហួសកំណត់នៅថ្ងៃ {0} គឺថ្ងៃបន្ទាប់ពីថ្ងៃកំណត់បង់។",
  ],
  // new
  void_banner: [
    "This Invoice is void. Nobody owes it. It stays here with its history.",
    "វិក្កយបត្រនេះទុកជាមោឃៈ។ គ្មាននរណាជំពាក់វាទេ។ វានៅទីនេះជាមួយប្រវត្តិរបស់វា។",
  ],
  // new
  draft_banner: [
    "This is a Draft. It has no Due Date and is not owed until it is issued.",
    "នេះជាសេចក្តីព្រាង។ វាគ្មានថ្ងៃកំណត់បង់ ហើយមិនទាន់ជំពាក់ រហូតដល់ចេញ។",
  ],
  is_t: ["Invoice status", "ស្ថានភាពវិក្កយបត្រ"],
  is_billed: ["Amount billed", "ចំនួនគិតថ្លៃ"],
  is_received: ["Received", "បានទទួល"],
  is_overdue_amt: ["Overdue now", "ហួសកំណត់ឥឡូវនេះ"],
  balance_due: ["Balance due", "សមតុល្យត្រូវបង់"],
  is_days: ["days", "ថ្ងៃ"],
  is_past_due: ["Days past the Due Date", "ថ្ងៃហួសថ្ងៃកំណត់បង់"],
  is_until_due: ["Days until the Due Date", "ថ្ងៃនៅសល់ដល់ថ្ងៃកំណត់បង់"],
  // new: the server does not say on which day the last payment came, so the line names no day
  is_paid_full: ["Paid in full", "បង់គ្រប់ចំនួន"],
  is_issued: ["Issued", "ចេញ"],
  is_due: ["Due", "កំណត់បង់"],
  is_today: ["Today (day +{0})", "ថ្ងៃនេះ (ថ្ងៃទី +{0})"],
  is_now: ["Today", "ថ្ងៃនេះ"],
  lines_t: ["What is billed", "អ្វីដែលបានគិតថ្លៃ"],
  // new
  line_adjusted: ["Was {0}", "ពីមុន {0}"],
  // new
  adjusted_total: ["Total after adjustments", "សរុបក្រោយកែតម្រូវ"],
  history_t: ["History", "ប្រវត្តិ"],
  // new
  h_made: ["Invoice made", "បានបង្កើតវិក្កយបត្រ"],
  h_overdue: ["Became overdue with {0} unpaid", "ហួសកំណត់ ដោយនៅជំពាក់ {0}"],
  // new
  h_adjusted: ["Adjusted: {0}", "បានកែតម្រូវ៖ {0}"],
  // new
  h_voided: ["Voided: {0}", "ទុកជាមោឃៈ៖ {0}"],
  cust_t: ["Customer", "អតិថិជន"],
  // new
  open_customer: ["Open Customer", "បើកអតិថិជន"],
  // new
  act_print: ["Print Invoice", "បោះពុម្ពវិក្កយបត្រ"],
  open_lease: ["Open Lease", "បើកកិច្ចសន្យា"],
  // new
  all_for: ["All Invoices for {0}", "វិក្កយបត្រទាំងអស់សម្រាប់ {0}"],
  // new
  all_for_cust: [
    "All Invoices of this Customer",
    "វិក្កយបត្រទាំងអស់របស់អតិថិជននេះ",
  ],
  // new
  records: ["Earlier forms", "ទម្រង់មុន"],
  // new
  records_note: [
    "Create Invoice, issue, adjust, void and billing runs, in English, until the next steps move them into this screen.",
    "បង្កើតវិក្កយបត្រ ចេញ កែតម្រូវ ទុកជាមោឃៈ និងការចេញវិក្កយបត្រ ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ផ្លាស់វាមកអេក្រង់នេះ។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type InvoicesTextKey = keyof typeof TEXT;

export function ivt(
  language: Language,
  key: InvoicesTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}
