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
  act_receive: ["Receive payment", "ទទួលការបង់ប្រាក់"],
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
  ni_btn: ["Create Invoice", "បង្កើតវិក្កយបត្រ"],
  ni_intro: [
    "For a one-time charge only. Rent and Utility Invoices are made by the app on the 25th.",
    "សម្រាប់ថ្លៃមួយដងប៉ុណ្ណោះ។ វិក្កយបត្រថ្លៃឈ្នួល និងទឹកភ្លើង កម្មវិធីចេញនៅថ្ងៃទី25។",
  ],
  ni_kind: ["Kind of charge", "ប្រភេទថ្លៃ"],
  // Changed from the mock-up: Move-out is built after slice 11, not "in round 3".
  ni_damage: [
    "A Damage charge comes from a finding in a Move-out inspection, and is entered there.",
    "ថ្លៃការខូចខាតមកពីការរកឃើញក្នុងការត្រួតពិនិត្យពេលចាកចេញ ហើយបញ្ចូលនៅទីនោះ។",
  ],
  f_customer: ["Customer", "អតិថិជន"],
  f_choose: ["Choose a Customer", "ជ្រើសរើសអតិថិជន"],
  // new
  ni_cust_help: [
    "Customers with a signed Lease. The charge goes on their newest Lease.",
    "អតិថិជនដែលមានកិច្ចសន្យាបានចុះហត្ថលេខា។ ថ្លៃនេះដាក់លើកិច្ចសន្យាថ្មីបំផុតរបស់គេ។",
  ],
  required: ["Required", "ចាំបាច់"],
  ni_desc: ["What is charged", "ថ្លៃអ្វី"],
  ni_desc_help: [
    "Printed on the Invoice. For example: Replacement key card.",
    "បោះពុម្ពលើវិក្កយបត្រ។ ឧទាហរណ៍៖ កាតសោជំនួស។",
  ],
  ni_amt: ["Amount", "ចំនួនទឹកប្រាក់"],
  ni_amt_help: [
    "One-time charges are in US dollars.",
    "ថ្លៃមួយដងគិតជាដុល្លារអាមេរិក។",
  ],
  ni_reason: ["Reason", "មូលហេតុ"],
  ni_src: ["What approves it", "អ្វីដែលអនុម័ត"],
  ni_src_help: [
    "The paper or message that allows this charge. For example: Signed key-card form, 02/11/2026.",
    "ឯកសារ ឬសារដែលអនុញ្ញាតថ្លៃនេះ។ ឧទាហរណ៍៖ ទម្រង់កាតសោដែលបានចុះហត្ថលេខា 02/11/2026។",
  ],
  ni_err_cust: ["Choose the Customer.", "សូមជ្រើសរើសអតិថិជន។"],
  ni_err_desc: ["Write what is charged.", "សូមសរសេរថ្លៃអ្វី។"],
  err_amount: [
    "Enter the amount in dollars and cents, for example 353.00.",
    "សូមបញ្ចូលចំនួនជាដុល្លារ និងសេន ឧទាហរណ៍ 353.00។",
  ],
  ni_err_reason: ["Write the reason.", "សូមសរសេរមូលហេតុ។"],
  ni_err_src: [
    "Write what approves this charge.",
    "សូមសរសេរអ្វីដែលអនុម័តថ្លៃនេះ។",
  ],
  // Changed from the mock-up: "saving" instead of "recording".
  err_sum: [
    "Fix {0} thing(s) before saving.",
    "សូមកែ {0} ចំណុច មុនពេលរក្សាទុក។",
  ],
  ni_submit: ["Save Draft Invoice", "រក្សាទុកសេចក្តីព្រាងវិក្កយបត្រ"],
  cancel: ["Cancel", "បោះបង់"],
  ni_what_t: ["What happens next", "អ្វីកើតឡើងបន្ទាប់"],
  ni_w1: [
    "The Invoice is saved as a Draft. It is not sent and not owed yet.",
    "វិក្កយបត្ររក្សាទុកជាសេចក្តីព្រាង។ មិនទាន់ផ្ញើ ហើយមិនទាន់ជំពាក់។",
  ],
  ni_w2: [
    "A Manager checks it and issues it. Then it gets its Invoice number.",
    "អ្នកគ្រប់គ្រងពិនិត្យ ហើយចេញវា។ ពេលនោះវាទទួលលេខវិក្កយបត្រ។",
  ],
  // Changed from the mock-up: the number of days is a Settings value the screen cannot read yet.
  ni_w3: [
    "The Due Date follows the Settings rule for one-time charges (7 days after the issue date unless it was changed). A Manager can choose another date, with a reason.",
    "ថ្ងៃកំណត់បង់តាមច្បាប់ក្នុងការកំណត់សម្រាប់ថ្លៃមួយដង (7 ថ្ងៃក្រោយថ្ងៃចេញ លើកលែងតែបានប្តូរ)។ អ្នកគ្រប់គ្រងអាចជ្រើសថ្ងៃផ្សេង ដោយមានមូលហេតុ។",
  ],
  ni_w4: [
    "Everything is saved in History.",
    "អ្វីៗទាំងអស់រក្សាទុកក្នុងប្រវត្តិ។",
  ],
  ni_dlg_t: ["Save this Draft Invoice?", "រក្សាទុកសេចក្តីព្រាងវិក្កយបត្រនេះ?"],
  ni_dlg_c: [
    "The Customer does not owe it until a Manager issues it. This is saved in History.",
    "អតិថិជនមិនទាន់ជំពាក់ រហូតដល់អ្នកគ្រប់គ្រងចេញវា។ ការនេះរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  ni_done_t: ["Draft Invoice saved", "បានរក្សាទុកសេចក្តីព្រាងវិក្កយបត្រ"],
  ni_done_b: [
    "Draft for {0}, {1}: {2}, {3}. A Manager checks it and issues it.",
    "សេចក្តីព្រាងសម្រាប់ {0} {1}៖ {2} {3}។ អ្នកគ្រប់គ្រងពិនិត្យ ហើយចេញវា។",
  ],
  ni_open: ["Open Draft", "បើកសេចក្តីព្រាង"],
  ni_to_list: ["Back to Invoices", "ត្រឡប់ទៅវិក្កយបត្រ"],
  // new
  ni_none: [
    "No Customer has a signed Lease yet, so there is no one to charge.",
    "មិនទាន់មានអតិថិជនណាមានកិច្ចសន្យាបានចុះហត្ថលេខាទេ ដូច្នេះគ្មាននរណាត្រូវគិតថ្លៃ។",
  ],
  // new
  unknown: [
    "We could not tell if this was saved. Press the button again: it is saved only once.",
    "យើងមិនដឹងថាបានរក្សាទុកឬនៅ។ សូមចុចប៊ូតុងម្តងទៀត៖ វារក្សាទុកតែម្តងប៉ុណ្ណោះ។",
  ],
  // new
  refused: [
    "This was not saved. The app did not accept it. Check what you typed, or ask the Owner if you may do this.",
    "ការនេះមិនបានរក្សាទុកទេ។ កម្មវិធីមិនទទួលយក។ សូមពិនិត្យអ្វីដែលបានវាយ ឬសួរម្ចាស់ថាអ្នកអាចធ្វើការនេះបានឬទេ។",
  ],
  // new
  changed: [
    "This Invoice changed meanwhile. It is shown again as it is now; check it and try again.",
    "វិក្កយបត្រនេះបានផ្លាស់ប្តូរក្នុងពេលនេះ។ វាបង្ហាញម្តងទៀតតាមស្ថានភាពឥឡូវ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  act_issue: ["Issue Invoice", "ចេញវិក្កយបត្រ"],
  // new
  iss_t: ["Issue this Invoice?", "ចេញវិក្កយបត្រនេះ?"],
  // new
  iss_b: [
    "It gets its Invoice number now, and {0} owes {1}. An issued Invoice cannot be changed, only adjusted or voided.",
    "វាទទួលលេខវិក្កយបត្រឥឡូវនេះ ហើយ {0} ជំពាក់ {1}។ វិក្កយបត្រដែលបានចេញមិនអាចកែបានទេ មានតែកែតម្រូវ ឬទុកជាមោឃៈ។",
  ],
  // new
  iss_rule: [
    "The Due Date follows the Settings rule.",
    "ថ្ងៃកំណត់បង់តាមច្បាប់ក្នុងការកំណត់។",
  ],
  // new
  iss_other: ["Choose another Due Date", "ជ្រើសថ្ងៃកំណត់បង់ផ្សេង"],
  // new
  iss_date: ["Due Date", "ថ្ងៃកំណត់បង់"],
  // new
  iss_reason: ["Why this date", "ហេតុអ្វីថ្ងៃនេះ"],
  // new
  iss_err_date: [
    "Choose a Due Date from today on.",
    "សូមជ្រើសថ្ងៃកំណត់បង់ចាប់ពីថ្ងៃនេះទៅ។",
  ],
  // new
  iss_err_reason: [
    "Write why the Invoice has this Due Date.",
    "សូមសរសេរហេតុអ្វីវិក្កយបត្រមានថ្ងៃកំណត់បង់នេះ។",
  ],
  // new
  iss_done: ["Issued as {0}. Due on {1}.", "បានចេញជា {0}។ ត្រូវបង់ថ្ងៃ {1}។"],
  act_adjust: ["Adjust", "កែតម្រូវ"],
  act_void: ["Void", "ទុកជាមោឃៈ"],
  // new
  close: ["Close", "បិទ"],
  // new
  adj_t: ["Adjust {0}", "កែតម្រូវ {0}"],
  // new
  adj_note: [
    "The issued Invoice stays as it is. The Adjustment is a new record that raises or lowers one line, with its reason, in History.",
    "វិក្កយបត្រដែលបានចេញនៅដដែល។ ការកែតម្រូវជាកំណត់ត្រាថ្មីដែលបង្កើន ឬបន្ថយបន្ទាត់មួយ ជាមួយមូលហេតុ ក្នុងប្រវត្តិ។",
  ],
  // new
  adj_line: ["Which line", "បន្ទាត់ណា"],
  // new
  adj_dir: ["Change", "ការផ្លាស់ប្តូរ"],
  // new
  adj_credit: ["Lower the amount", "បន្ថយចំនួន"],
  // new
  adj_debit: ["Raise the amount", "បង្កើនចំនួន"],
  // new
  adj_live: ["{0} goes from {1} to {2}.", "{0} ប្តូរពី {1} ទៅ {2}។"],
  // new
  adj_save: ["Save Adjustment", "រក្សាទុកការកែតម្រូវ"],
  // new
  adj_err_dir: [
    "Choose Lower the amount or Raise the amount.",
    "សូមជ្រើសបន្ថយចំនួន ឬបង្កើនចំនួន។",
  ],
  // new
  adj_err_more: [
    "Enter an amount up to {0}, what the line is now.",
    "សូមបញ្ចូលចំនួនមិនលើស {0} ដែលបន្ទាត់មានឥឡូវ។",
  ],
  // new
  adj_err_src: [
    "Write what approves this Adjustment.",
    "សូមសរសេរអ្វីដែលអនុម័តការកែតម្រូវនេះ។",
  ],
  // new
  adj_err_paid: [
    "This line is paid in full, so it cannot be raised. Bill the missed amount with Create Invoice instead.",
    "បន្ទាត់នេះបានបង់គ្រប់ ដូច្នេះមិនអាចបង្កើនបានទេ។ សូមចេញវិក្កយបត្រសម្រាប់ចំនួនដែលខ្វះ ដោយប្រើបង្កើតវិក្កយបត្រ។",
  ],
  // new
  void_t: ["Void {0}?", "ទុក {0} ជាមោឃៈ?"],
  // new
  void_b: [
    "Nobody owes this Invoice after this; {0} stops being owed. It stays in the list and its History, marked Void. This cannot be undone.",
    "បន្ទាប់ពីនេះ គ្មាននរណាជំពាក់វិក្កយបត្រនេះទេ៖ {0} លែងជំពាក់។ វានៅក្នុងបញ្ជី និងប្រវត្តិ ដោយសម្គាល់ថាមោឃៈ។ មិនអាចត្រឡប់វិញបានទេ។",
  ],
  // new
  void_paid: [
    "Money was already paid toward this Invoice, so it cannot be voided. Move or return that payment first.",
    "មានប្រាក់បានបង់សម្រាប់វិក្កយបត្រនេះរួចហើយ ដូច្នេះមិនអាចទុកជាមោឃៈបានទេ។ សូមផ្លាស់ ឬប្រគល់ការបង់ប្រាក់នោះជាមុនសិន។",
  ],
  // new
  void_save: ["Void Invoice", "ទុកវិក្កយបត្រជាមោឃៈ"],
  // new
  void_err_reason: [
    "Write why this Invoice is voided.",
    "សូមសរសេរហេតុអ្វីវិក្កយបត្រនេះទុកជាមោឃៈ។",
  ],
  // new
  adj_done: ["Adjustment saved.", "បានរក្សាទុកការកែតម្រូវ។"],
  // new
  void_done: ["The Invoice is void.", "វិក្កយបត្រទុកជាមោឃៈហើយ។"],
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
    "Billing runs and Due Date settings, in English, until the next steps move them into this screen.",
    "ការចេញវិក្កយបត្រ និងការកំណត់ថ្ងៃកំណត់បង់ ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ផ្លាស់វាមកអេក្រង់នេះ។",
  ],
  // V1-058 R5d: the late-payment card and the Reduce or waive dialog (mock-up round 6, i18n6.js).
  lt_t: ["Late-payment charge", "ថ្លៃពិន័យបង់យឺត"],
  lt_CHARGED: ["Charged", "បានគិតថ្លៃ"],
  lt_REDUCED: ["Reduced", "បានកាត់បន្ថយ"],
  lt_WAIVED: ["Waived", "បានលើកលែង"],
  lt_PAID: ["Paid", "បានបង់"],
  lt_base: ["Unpaid on {0}", "មិនទាន់បង់នៅ {0}"],
  lt_added: ["Added ({0}%)", "បានបន្ថែម ({0}%)"],
  lt_added_s: ["Added by the app on {0}.", "បន្ថែមដោយកម្មវិធី នៅ {0}។"],
  // new: a charge from before the automatic pass was added by a person.
  lt_added_by: ["Added by {0} on {1}.", "បន្ថែមដោយ {0} នៅ {1}។"],
  // new
  lt_added_plain: ["Added", "បានបន្ថែម"],
  // new: an old correction that undid a reduction (before the automatic pass).
  lt_REVERSED: ["Reduction undone", "បានលុបការកាត់បន្ថយ"],
  // new
  lt_h_rev: [
    "Late-payment charge reduction undone: back to {0}, by {1}. {2}",
    "បានលុបការកាត់បន្ថយថ្លៃពិន័យ៖ ត្រឡប់ទៅ {0} ដោយ {1}។ {2}",
  ],
  // new
  lt_h_add_by: [
    "Late-payment charge {0} added by {1}",
    "ថ្លៃពិន័យ {0} បន្ថែមដោយ {1}",
  ],
  // new
  late_banner_by: [
    "This Invoice is overdue. A late-payment charge of {0} was added on {1}.",
    "វិក្កយបត្រនេះហួសកំណត់។ ថ្លៃពិន័យ {0} ត្រូវបានបន្ថែមនៅ {1}។",
  ],
  // new: the reduction command refuses a charge a Deposit paid (slice 11g-2).
  lt_dep_note: [
    "A Deposit paid part of this charge at the move-out, so it cannot be reduced here. Use a correction of the Final Settlement.",
    "ប្រាក់កក់បានបង់មួយផ្នែកនៃថ្លៃនេះពេលចេញ ដូច្នេះមិនអាចកាត់បន្ថយនៅទីនេះបានទេ។ សូមប្រើការកែតម្រូវនៃការទូទាត់ចុងក្រោយ។",
  ],
  lt_ch_s: ["By {0} on {1}. {2}", "ដោយ {0} នៅ {1}។ {2}"],
  lt_paid: ["Paid", "បានបង់"],
  lt_left: ["Still owed", "នៅជំពាក់"],
  // new
  lt_from_credit: ["Customer Credit", "ឥណទានអតិថិជន"],
  // new
  lt_from_deposit: ["Deposit", "ប្រាក់កក់"],
  lt_sep: [
    "A separate charge, payable now. It is not an Invoice and does not change {0}.",
    "ថ្លៃដាច់ដោយឡែក ត្រូវបង់ភ្លាម។ វាមិនមែនជាវិក្កយបត្រ ហើយមិនប្តូរ {0} ទេ។",
  ],
  lt_pay: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  lt_fix: ["Reduce or waive", "កាត់បន្ថយ ឬលើកលែង"],
  mgr_badge: ["MANAGER", "អ្នកគ្រប់គ្រង"],
  // new
  lt_locked: [
    "Only a Manager or the Owner can do this.",
    "មានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ទេដែលអាចធ្វើការនេះ។",
  ],
  lt_why_WRONG_INVOICE: [
    "Staff recorded the payment on the wrong Invoice",
    "បុគ្គលិកកត់ត្រាការបង់ទៅវិក្កយបត្រខុស",
  ],
  lt_why_PAID_ON_TIME_RECORDED_LATE: [
    "Paid on time but recorded late",
    "បានបង់ទាន់ពេល ប៉ុន្តែកត់ត្រាយឺត",
  ],
  lt_why_OTHER_STAFF_MISTAKE: ["Other staff mistake", "កំហុសបុគ្គលិកផ្សេងទៀត"],
  late_banner_auto: [
    "This Invoice is overdue. The app added a late-payment charge of {0} on {1}.",
    "វិក្កយបត្រនេះហួសកំណត់។ កម្មវិធីបានបន្ថែមថ្លៃពិន័យ {0} នៅ {1}។",
  ],
  lt_h_add: [
    "Late-payment charge {0} added by the app ({1}% of {2} unpaid)",
    "កម្មវិធីបានបន្ថែមថ្លៃពិន័យ {0} ({1}% នៃ {2} មិនទាន់បង់)",
  ],
  lt_h_red: [
    "Late-payment charge reduced to {0} by {1}. {2}",
    "ថ្លៃពិន័យបានកាត់បន្ថយមក {0} ដោយ {1}។ {2}",
  ],
  lt_h_waive: [
    "Late-payment charge waived by {1}. {2}",
    "ថ្លៃពិន័យបានលើកលែងដោយ {1}។ {2}",
  ],
  lt_h_paid: [
    "{0} paid to the late-payment charge from {1}",
    "បានបង់ {0} ទៅថ្លៃពិន័យ ពី {1}",
  ],
  lt_fix_t: [
    "Reduce or waive the late-payment charge on {0}",
    "កាត់បន្ថយ ឬលើកលែងថ្លៃពិន័យលើ {0}",
  ],
  lt_now: ["Charge now", "ថ្លៃពិន័យឥឡូវ"],
  lt_bal_at: [
    "Unpaid on the first overdue day",
    "មិនទាន់បង់នៅថ្ងៃដំបូងហួសកំណត់",
  ],
  lt_choice: ["Change", "ការប្តូរ"],
  lt_o_red: ["Reduce", "កាត់បន្ថយ"],
  lt_o_red_s: [
    "A smaller amount: at least {0} (already paid) and less than {1}.",
    "ចំនួនតិចជាង៖ យ៉ាងតិច {0} (បានបង់រួច) និងតិចជាង {1}។",
  ],
  lt_o_red_s0: [
    "A smaller amount, more than $0.00 and less than {0}.",
    "ចំនួនតិចជាង លើស $0.00 និងតិចជាង {0}។",
  ],
  lt_o_waive: ["Waive", "លើកលែង"],
  lt_o_waive_s: [
    "The charge becomes $0.00. Nothing is owed.",
    "ថ្លៃពិន័យក្លាយជា $0.00។ មិនជំពាក់អ្វីទេ។",
  ],
  // new: the owner's rule of round 6: Waive only while nothing is paid.
  lt_o_waive_no: [
    "Not possible: {0} is already paid.",
    "មិនអាចទេ៖ បានបង់ {0} រួចហើយ។",
  ],
  lt_red_amt: ["Reduced amount", "ចំនួនកាត់បន្ថយ"],
  lt_reason: ["Reason", "មូលហេតុ"],
  // new
  lt_reason_pick: ["Choose a reason", "ជ្រើសមូលហេតុ"],
  lt_detail: ["What happened", "អ្វីដែលបានកើតឡើង"],
  lt_detail_ph: [
    "For example: RCP260031 was recorded on INV260035 instead of INV260006",
    "ឧទាហរណ៍៖ RCP260031 ត្រូវបានកត់ត្រាលើ INV260035 ជំនួស INV260006",
  ],
  lt_prev_red: [
    "The charge goes from {0} to {1}. The Customer still owes {2} of it.",
    "ថ្លៃពិន័យពី {0} មក {1}។ អតិថិជននៅជំពាក់ {2}។",
  ],
  lt_prev_zero: [
    "The charge on {0} becomes $0.00. Nothing is owed.",
    "ថ្លៃពិន័យលើ {0} ក្លាយជា $0.00។ មិនជំពាក់អ្វីទេ។",
  ],
  lt_fix_note: [
    "Only after a Customer complaint about a staff mistake. The amount can only go down. The old amount and the reason stay in History.",
    "តែក្រោយអតិថិជនតវ៉ាអំពីកំហុសបុគ្គលិក។ ចំនួនអាចតែចុះ។ ចំនួនចាស់ និងមូលហេតុនៅក្នុងប្រវត្តិ។",
  ],
  lt_e_pick: ["Choose Reduce or Waive.", "សូមជ្រើស កាត់បន្ថយ ឬលើកលែង។"],
  lt_e_amt: [
    "Enter an amount more than $0.00 and less than {0}.",
    "សូមបញ្ចូលចំនួនលើស $0.00 និងតិចជាង {0}។",
  ],
  lt_e_amt_paid: [
    "Enter an amount of at least {0} and less than {1}.",
    "សូមបញ្ចូលចំនួនយ៉ាងតិច {0} និងតិចជាង {1}។",
  ],
  lt_e_reason: ["Choose a reason.", "សូមជ្រើសមូលហេតុ។"],
  lt_e_detail: ["Write what happened.", "សូមសរសេរអ្វីដែលបានកើតឡើង។"],
  // new
  lt_save: ["Save change", "រក្សាទុកការប្តូរ"],
  lt_saved: [
    "Late-payment charge changed for {0}.",
    "បានប្តូរថ្លៃពិន័យសម្រាប់ {0}។",
  ],
  // new
  lt_failed: [
    "The late-payment charge could not be read just now.",
    "មិនអាចអានថ្លៃពិន័យបានទេឥឡូវនេះ។",
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
