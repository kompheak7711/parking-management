// V1-058 R5c: the words of the Payments screens in English and Khmer, from the owner's mock-up
// (i18n.js, i18n6.js). Khmer needs the native check before the app is used. Lines marked "new"
// are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  pay_title: ["Payments", "ការបង់ប្រាក់"],
  rp_title: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  rp_intro: [
    "Record money only after it has arrived. Check the ABA app or count the cash first.",
    "កត់ត្រាតែប្រាក់ដែលបានទទួលពិតប្រាកដ។ ពិនិត្យកម្មវិធី ABA ឬរាប់សាច់ប្រាក់ជាមុនសិន។",
  ],
  back: ["Back", "ត្រឡប់ក្រោយ"],
  clear: ["Clear", "សម្អាត"],
  cancel: ["Cancel", "បោះបង់"],
  required: ["Required", "ចាំបាច់"],
  optional: ["Optional", "មិនចាំបាច់"],
  // new
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  // new
  failed: [
    "This could not be read just now. Check the connection and try again.",
    "មិនអាចអានបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  // new
  unknown_customer: ["Customer", "អតិថិជន"],
  f_customer: ["Customer", "អតិថិជន"],
  f_choose: ["Choose a Customer", "ជ្រើសរើសអតិថិជន"],
  f_currency: ["Currency", "រូបិយប័ណ្ណ"],
  cur_USD: ["US dollar", "ដុល្លារ"],
  cur_KHR: ["Riel", "រៀល"],
  f_amount: ["Amount received", "ចំនួនទឹកប្រាក់ដែលបានទទួល"],
  f_method: ["Payment method", "វិធីបង់ប្រាក់"],
  f_when: ["Received on", "កាលបរិច្ឆេទទទួល"],
  f_when_help: [
    "Day/month/year and 24-hour time, Phnom Penh time.",
    "ថ្ងៃ/ខែ/ឆ្នាំ និងម៉ោង 24 ម៉ោង តាមម៉ោងភ្នំពេញ។",
  ],
  // new: one field for every method that needs a reference
  f_ref: ["Transaction number or reference", "លេខប្រតិបត្តិការ ឬលេខយោង"],
  f_note: ["Payer note", "កំណត់សម្គាល់អ្នកបង់"],
  f_note_help: [
    "What the payer wrote in the payment note, for example the Invoice number.",
    "អ្វីដែលអ្នកបង់បានសរសេរក្នុងកំណត់សម្គាល់ ដូចជាលេខវិក្កយបត្រ។",
  ],
  rp_submit: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  err_sum: [
    "Fix {0} thing(s) before recording.",
    "សូមកែ {0} ចំណុច មុនពេលកត់ត្រា។",
  ],
  err_cust: ["Choose who paid.", "សូមជ្រើសរើសអ្នកបង់។"],
  err_amount: [
    "Enter the amount in dollars and cents, for example 353.00.",
    "សូមបញ្ចូលចំនួនជាដុល្លារ និងសេន ឧទាហរណ៍ 353.00។",
  ],
  err_amount_khr: [
    "Enter whole riel without decimals, for example 184263.",
    "សូមបញ្ចូលចំនួនរៀលគត់ ឧទាហរណ៍ 184263។",
  ],
  // new: riel counts at the app rate, so it must be what a dollar-and-cent amount costs
  err_riel_grid: [
    "At the app rate, {0} ៛ is not an exact dollar amount. Enter {1} ៛ ({2}) or {3} ៛ ({4}).",
    "តាមអត្រាកម្មវិធី {0} ៛ មិនមែនជាចំនួនដុល្លារគត់ទេ។ សូមបញ្ចូល {1} ៛ ({2}) ឬ {3} ៛ ({4})។",
  ],
  // new
  unit: ["Unit", "បន្ទប់"],
  // new
  phone: ["Phone", "ទូរស័ព្ទ"],
  // new
  unpaid: ["Unpaid", "មិនទាន់បង់"],
  // new
  err_method: ["Choose how the money was paid.", "សូមជ្រើសរើសវិធីបង់ប្រាក់។"],
  // new
  err_ref: [
    "Enter the transaction number or reference.",
    "សូមបញ្ចូលលេខប្រតិបត្តិការ ឬលេខយោង។",
  ],
  err_when: [
    "Use day/month/year and 24-hour time, for example 03/11/2026, 10:24.",
    "សូមប្រើ ថ្ងៃ/ខែ/ឆ្នាំ និងម៉ោង 24 ម៉ោង ឧទាហរណ៍ 03/11/2026, 10:24។",
  ],
  err_future: [
    "This is later than now. Record money only after it arrives.",
    "ពេលវេលានេះក្រោយពេលបច្ចុប្បន្ន។ កត់ត្រាតែប្រាក់ដែលបានទទួលរួច។",
  ],
  // new
  err_rate: [
    "Today's riel rate is not available yet. Record the payment in US dollars, or try again later.",
    "អត្រារៀលថ្ងៃនេះមិនទាន់មានទេ។ សូមកត់ត្រាជាដុល្លារ ឬព្យាយាមម្តងទៀតពេលក្រោយ។",
  ],
  pf_t: ["What this money pays for", "ប្រាក់នេះបង់សម្រាប់អ្វី"],
  pf_help: [
    "The app ticks the oldest Due Date first. Change the ticks only if the Customer names an Invoice; the amount follows the ticks. Saving pays them at once.",
    "កម្មវិធីធីកវិក្កយបត្រដែលមានថ្ងៃកំណត់បង់ចាស់ជាងគេមុន។ ប្តូរការធីក លុះត្រាតែអតិថិជនប្រាប់វិក្កយបត្រជាក់លាក់។ ចំនួនទឹកប្រាក់តាមការធីក។ ពេលរក្សាទុក វាបង់ភ្លាមៗ។",
  ],
  pf_help_own: [
    "You changed the ticks, so the amount is their total. Saving pays the ticked Invoices at once.",
    "អ្នកបានប្តូរការធីក។ ពេលរក្សាទុក វាបង់វិក្កយបត្រដែលបានធីកភ្លាមៗ។",
  ],
  pfl_hint: [
    "A late-payment charge is paid right after its own Invoice.",
    "ថ្លៃពិន័យត្រូវបង់បន្ទាប់ពីវិក្កយបត្ររបស់វាភ្លាម។",
  ],
  pf_oldest: ["Back to oldest first", "ត្រឡប់ទៅចាស់ជាងគេមុនវិញ"],
  pf_pays: ["Pays {0}", "បង់ {0}"],
  pf_owed: ["{0} owed", "ជំពាក់ {0}"],
  due_on: ["Due date", "ថ្ងៃកំណត់បង់"],
  pfl_row: ["Late-payment charge", "ថ្លៃពិន័យបង់យឺត"],
  pfl_on: [
    "on {0} · not an Invoice · payable now · owed {1}",
    "លើ {0} · មិនមែនវិក្កយបត្រ · ត្រូវបង់ភ្លាម · ជំពាក់ {1}",
  ],
  pfl_d: ["Late-payment charge on {0}", "ថ្លៃពិន័យបង់យឺត លើ {0}"],
  pf_amt_first: [
    "Enter the amount first. The app then ticks the oldest Due Date first.",
    "សូមបញ្ចូលចំនួនទឹកប្រាក់ជាមុនសិន។ បន្ទាប់មក កម្មវិធីធីកថ្ងៃកំណត់បង់ចាស់ជាងគេមុន។",
  ],
  pf_all_used: ["All the money is used.", "ប្រាក់ទាំងអស់ត្រូវបានប្រើ។"],
  pf_left: [
    "Left over: {0}. Ask the Customer: keep it as Credit, or refund it.",
    "នៅសល់៖ {0}។ សូមសួរអតិថិជន៖ រក្សាទុកជាឥណទាន ឬសងប្រាក់វិញ។",
  ],
  pf_left_more: [
    "{0} is left. Tick another Invoice.",
    "នៅសល់ {0}។ សូមធីកវិក្កយបត្រមួយទៀត។",
  ],
  pf_nocust: ["Choose the Customer first.", "សូមជ្រើសរើសអតិថិជនជាមុនសិន។"],
  pf_none: [
    "This Customer has nothing unpaid. The money waits on the Receipt. Ask the Customer: keep it as Credit for the next Invoice, or refund it.",
    "អតិថិជននេះគ្មានអ្វីមិនទាន់បង់ទេ។ ប្រាក់រង់ចាំលើបង្កាន់ដៃ។ សូមសួរអតិថិជន៖ រក្សាទុកជាឥណទានសម្រាប់វិក្កយបត្របន្ទាប់ ឬសងប្រាក់វិញ។",
  ],
  pf_err_pick: [
    "Tick at least one Invoice. Money pays Invoices when it is received.",
    "សូមធីកវិក្កយបត្រយ៉ាងហោចណាស់មួយ។ ប្រាក់បង់វិក្កយបត្រនៅពេលទទួល។",
  ],
  pf_err_zero: [
    "{0} gets nothing from this money. Untick it.",
    "{0} មិនបានប្រាក់ពីការបង់នេះទេ។ សូមដកធីកចេញ។",
  ],
  pf_err_zero_l: [
    "The money is used up before the late-payment charge on {0}. Untick it or enter more.",
    "ប្រាក់អស់មុនដល់ថ្លៃពិន័យលើ {0}។ ដោះធីក ឬបញ្ចូលបន្ថែម។",
  ],
  pf_err_more: [
    "{0} is left and other Invoices are still unpaid. Tick another Invoice.",
    "នៅសល់ {0} ហើយវិក្កយបត្រផ្សេងទៀតមិនទាន់បង់។ សូមធីកវិក្កយបត្រមួយទៀត។",
  ],
  pf_two: [
    "The payment and what it pays for are saved as two separate records in History.",
    "ការបង់ប្រាក់ និងអ្វីដែលវាបង់ ត្រូវរក្សាទុកជាកំណត់ត្រាពីរដាច់ដោយឡែកក្នុងប្រវត្តិ។",
  ],
  pf_kept: [
    "Nothing to pay yet. {0} waits on the Receipt. Ask the Customer: keep it as Credit, or refund it.",
    "មិនទាន់មានអ្វីត្រូវបង់។ {0} រង់ចាំលើបង្កាន់ដៃ។ សូមសួរអតិថិជន៖ រក្សាទុកជាឥណទាន ឬសងប្រាក់វិញ។",
  ],
  pf_left_t: ["Left over", "នៅសល់"],
  pf_ask: [
    "Ask the Customer: keep it as Credit, or refund it.",
    "សូមសួរអតិថិជន៖ រក្សាទុកជាឥណទាន ឬសងប្រាក់វិញ។",
  ],
  rc_matched_to: ["Paid for", "បង់សម្រាប់"],
  fx_system: ["App rate (rounded up)", "អត្រាកម្មវិធី (បង្គត់ឡើង)"],
  fx_usd: ["Worth in US dollars", "តម្លៃជាដុល្លារ"],
  dlg_pay_t: ["Receive this payment?", "ទទួលការបង់ប្រាក់នេះ?"],
  // changed: the Receipt number is given by the server when it is saved
  dlg_pay_c: [
    "This makes a Receipt. A recorded payment cannot be edited. If something is wrong later, a Manager reverses it with a reason.",
    "ការនេះបង្កើតបង្កាន់ដៃ។ ការបង់ប្រាក់ដែលបានកត់ត្រាមិនអាចកែបានទេ។ បើមានកំហុសពេលក្រោយ អ្នកគ្រប់គ្រងបញ្ច្រាសវាដោយមានមូលហេតុ។",
  ],
  done_pay_t: ["Payment recorded", "បានកត់ត្រាការបង់ប្រាក់"],
  done_pay_kept: [
    "{0} from {1}. Receipt {2} is ready. Nothing to pay yet: ask the Customer to keep it as Credit, or refund it.",
    "{0} ពី {1}។ បង្កាន់ដៃ {2} រួចរាល់។ មិនទាន់មានអ្វីត្រូវបង់៖ សូមសួរអតិថិជនថា រក្សាទុកជាឥណទាន ឬសងប្រាក់វិញ។",
  ],
  done_pay_paid: [
    "{0} from {1}. Receipt {2} is ready. It paid {3}.",
    "{0} ពី {1}។ បង្កាន់ដៃ {2} រួចរាល់។ វាបានបង់ {3}។",
  ],
  // new
  done_again: ["Receive another payment", "ទទួលការបង់ប្រាក់មួយទៀត"],
  // new
  out_unknown: [
    "No answer came back, so it is not known whether the payment was saved. Press Receive payment again: the same payment is saved only once.",
    "មិនមានចម្លើយត្រឡប់មកទេ ដូច្នេះមិនដឹងថាការបង់ប្រាក់ត្រូវបានរក្សាទុកឬអត់។ សូមចុចទទួលការបង់ប្រាក់ម្តងទៀត៖ ការបង់ប្រាក់ដដែលត្រូវរក្សាទុកតែម្តង។",
  ],
  // new
  out_refused: [
    "The payment was not saved. Check the values and try again.",
    "ការបង់ប្រាក់មិនត្រូវបានរក្សាទុកទេ។ សូមពិនិត្យតម្លៃ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  out_changed: [
    "This Customer's Invoices changed meanwhile, so nothing was saved. The list now shows what is owed; check the ticks and press Receive payment again.",
    "វិក្កយបត្ររបស់អតិថិជននេះបានប្តូរ ដូច្នេះគ្មានអ្វីត្រូវរក្សាទុកទេ។ បញ្ជីឥឡូវបង្ហាញអ្វីដែលជំពាក់ សូមពិនិត្យការធីក ហើយចុចទទួលការបង់ប្រាក់ម្តងទៀត។",
  ],
  // new
  out_too_many: [
    "This Customer owes more than 100 items. Tick only what the Customer names.",
    "អតិថិជននេះជំពាក់ច្រើនជាង 100 មុខ។ សូមធីកតែអ្វីដែលអតិថិជនប្រាប់។",
  ],
  // new
  out_reused: [
    "These values changed after a press with no answer. Press Clear and enter the payment again.",
    "តម្លៃបានប្តូរក្រោយការចុចដែលគ្មានចម្លើយ។ សូមចុចសម្អាត ហើយបញ្ចូលការបង់ប្រាក់ម្តងទៀត។",
  ],
  RENT: ["Rent", "ថ្លៃឈ្នួល"],
  UTILITIES: ["Utilities", "ថ្លៃទឹកភ្លើង"],
  // new
  SERVICE_CHARGES: ["Services", "សេវា"],
  MISCELLANEOUS_CHARGES: ["Miscellaneous", "ផ្សេងៗ"],
  DAMAGE_CHARGES: ["Damage", "ការខូចខាត"],
  // new
  records: ["Earlier forms", "ទម្រង់មុន"],
  // new
  records_note: [
    "Payment lists, matching, Credit and refunds, in English, until the next steps move them into this screen.",
    "បញ្ជីការបង់ប្រាក់ ការផ្គូផ្គង ឥណទាន និងការសងប្រាក់ ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ផ្លាស់វាមកអេក្រង់នេះ។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type PaymentsTextKey = keyof typeof TEXT;

export function pyt(
  language: Language,
  key: PaymentsTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}
