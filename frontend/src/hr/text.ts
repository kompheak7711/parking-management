// HRIS phase 6: the words of Office › Employees and payroll, in English and Khmer, from the
// HR mock-up rounds 23, 26, 27 and 30 (owner-approved words) and the Khmer check sheet
// /mnt/project-files/v1-1/hris/hr-words-khmer-check-2026-11-03.xlsx. Khmer marked "new" is not
// in that sheet and needs the native check, like every Khmer text before the app is used.

import type { Language } from "../signInText";
import { singular } from "../shell/plural";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: [
    "This could not be loaded.",
    // new
    "មិនអាចអានបានទេឥឡូវនេះ។",
  ],
  retry: ["Try again", "សាកម្តងទៀត"],
  no_property: ["Choose a property first.", "សូមជ្រើសរើសអចលនទ្រព្យជាមុនសិន។"],
  cancel: ["Cancel", "បោះបង់"],
  close: ["Close", "បិទ"],
  save: ["Save", "រក្សាទុក"],
  required: ["Required", "ចាំបាច់"],
  optional: ["Optional", "ស្រេចចិត្ត"],
  yes: ["Yes", "បាទ/ចាស"],
  no: ["No", "ទេ"],
  reason: ["Reason", "មូលហេតុ"],
  say_why: ["Enter a reason.", "សូមប្រាប់មូលហេតុ។"],
  // new
  f_right: [
    "You do not have permission to do this.",
    "អ្នកមិនមានសិទ្ធិធ្វើការនេះទេ។",
  ],
  // new
  f_failed: ["This was not saved. Try again.", "មិនបានរក្សាទុកទេ។ សាកម្តងទៀត។"],
  // new
  f_refused: ["This could not be saved: {0}", "កម្មវិធីបានបដិសេធ៖ {0}"],
  // new
  f_stale: [
    "Someone else changed this. Reload it and try again.",
    "មាននរណាម្នាក់បានកែរួចហើយ។ សូមបើកម្តងទៀត។",
  ],
  not_found: [
    "This was not found.",
    // new
    "រកមិនឃើញទេ។",
  ],
  amount_bad: [
    "Enter an amount, for example 120.00.",
    // new
    "វាយចំនួនដូចជា 120.00។",
  ],
  day_bad: [
    "Choose a date.",
    // new
    "សូមជ្រើសថ្ងៃ។",
  ],
  time_bad: ["Enter a time, for example 07:05.", "វាយម៉ោងដូចជា 07:05។"],
  nothing: ["None.", "គ្មាន។"],
  by: ["By {0}, {1}", "ដោយ {0} {1}"],
  per_month: ["{0} a month", "{0} ក្នុងមួយខែ"],

  // Names
  sh_MORNING: ["Morning shift", "វេនព្រឹក"],
  sh_AFTERNOON: ["Afternoon shift", "វេនរសៀល"],
  sh_NIGHT: ["Night shift", "វេនយប់"],
  sh_OFFICE: [
    "Office hours (7:00–11:00, 13:00–17:00)",
    // new
    "ម៉ោងការិយាល័យ 7:00-11:00, 13:00-17:00",
  ],
  shs_MORNING: ["Morning", "ព្រឹក"],
  shs_AFTERNOON: ["Afternoon", "រសៀល"],
  shs_NIGHT: ["Night", "យប់"],
  shs_OFFICE: [
    "Office",
    // new
    "ការិយាល័យ",
  ],
  rr_CLEANER: ["Cleaner reports", "របាយការណ៍អ្នកសម្អាត"],
  rr_TECHNICIAN: ["Technician reports", "របាយការណ៍ជាង"],
  rr_CARETAKER: ["Caretaker reports", "របាយការណ៍អ្នកថែទាំ"],
  rr_METER_READER: ["Meter reader reports", "របាយការណ៍អ្នកអានកុងទ័រ"],
  rr_AUTHORIZER: [
    "Authorizer (approves reports)",
    "អ្នកអនុម័ត (អនុម័តរបាយការណ៍)",
  ],
  pm_CASH_USD: ["Cash", "សាច់ប្រាក់"],
  pm_ABA: ["ABA account", "គណនី ABA"],
  pm_ABA_JOINT: ["1020 · Joint ABA account", "1020 · គណនី ABA រួម"],
  wd_1: ["Monday", "ថ្ងៃច័ន្ទ"],
  wd_2: ["Tuesday", "ថ្ងៃអង្គារ"],
  wd_3: ["Wednesday", "ថ្ងៃពុធ"],
  wd_4: ["Thursday", "ថ្ងៃព្រហស្បតិ៍"],
  wd_5: ["Friday", "ថ្ងៃសុក្រ"],
  wd_6: ["Saturday", "ថ្ងៃសៅរ៍"],
  wd_7: ["Sunday", "ថ្ងៃអាទិត្យ"],
  wds_1: ["Mon", "ច"],
  wds_2: ["Tue", "អ"],
  wds_3: ["Wed", "ពុ"],
  wds_4: ["Thu", "ព្រ"],
  wds_5: ["Fri", "សុ"],
  wds_6: ["Sat", "ស"],
  wds_7: ["Sun", "អា"],

  // Employees
  e_title: ["Employees", "បុគ្គលិក"],
  e_sub: [
    "Staff details, job titles, Telegram link and employment history.",
    "ព័ត៌មានបុគ្គលិក ការងារ ការភ្ជាប់ Telegram និងប្រវត្តិ។",
  ],
  e_add: ["Add employee", "បន្ថែមបុគ្គលិក"],
  e_active: ["Active", "សកម្ម"],
  e_left: ["Past employees", "បានចាកចេញ"],
  e_never: [
    "Employees are never deleted. When someone leaves, they move to Past employees.",
    "បុគ្គលិកមិនដែលត្រូវលុបទេ។ អ្នកចាកចេញ ផ្លាស់ទៅ បានចាកចេញ។",
  ],
  e_none: ["No employees yet.", "មិនទាន់មានបុគ្គលិក។"],
  e_name: ["Name", "ឈ្មោះ"],
  e_name_en: ["Name in English", "ឈ្មោះជាអង់គ្លេស"],
  e_name_km: ["Name in Khmer", "ឈ្មោះជាខ្មែរ"],
  e_phone: ["Phone", "ទូរស័ព្ទ"],
  e_signin: ["App sign-in", "គណនីចូលកម្មវិធី"],
  e_no_signin: ["No app sign-in", "គ្មានគណនីចូលកម្មវិធី"],
  e_start: ["Start date", "ថ្ងៃចាប់ផ្ដើម"],
  e_end: ["End date", "ថ្ងៃបញ្ចប់"],
  e_job: ["Job title", "ការងារ"],
  e_shift: ["Regular shift", "វេនធម្មតា"],
  e_dayoff: ["Regular day off", "ថ្ងៃឈប់ធម្មតា"],
  e_hours: [
    "Working hours",
    // new
    "ម៉ោងធ្វើការ",
  ],
  e_office_hours: [
    "Office hours: 7:00 to 11:00 and 13:00 to 17:00. Lateness is counted from 7:00.",
    // new
    "ម៉ោងការិយាល័យ៖ 7:00 ដល់ 11:00 និង 13:00 ដល់ 17:00។ យឺតរាប់ពី 7:00។",
  ],
  e_monthly_off: [
    "No regular day off: days off are taken on request, up to {0} per month. Mark each one on the Weekly plan.",
    // new
    "គ្មានថ្ងៃឈប់ធម្មតាទេ៖ ឈប់ {0} ថ្ងៃក្នុងមួយខែ នៅពេលបុគ្គលិកស្នើសុំ។ សូមកត់ថ្ងៃនីមួយៗក្នុងផែនការប្រចាំសប្ដាហ៍។",
  ],
  e_id_head: [
    "ID details",
    // new
    "ព័ត៌មានអត្តសញ្ញាណ",
  ],
  e_id_number: [
    "ID card or passport number",
    // new
    "លេខអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែន",
  ],
  e_id_photo: [
    "Photo of the ID card or passport",
    // new
    "រូបថតអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែន",
  ],
  e_id_photo_note: [
    "JPG, PNG or PDF, up to 15 MB.",
    // new
    "JPG, PNG ឬ PDF ធំបំផុត 15 MB។",
  ],
  e_id_photo_big: [
    "The file is larger than 15 MB. Choose a smaller file.",
    // new
    "ឯកសារធំជាង 15 MB។",
  ],
  e_id_need: [
    "Enter the ID type and number, date and place of birth and home address, and add the ID photo.",
    // new
    "សូមបញ្ចូលប្រភេទ និងលេខអត្តសញ្ញាណ ថ្ងៃខែឆ្នាំកំណើត ទីកន្លែងកំណើត អាសយដ្ឋានផ្ទះ ហើយបន្ថែមរូបថតអត្តសញ្ញាណ។",
  ],
  e_from: ["From", "ចាប់ពី"],
  e_leaves: ["Leaves {0}", "ចាកចេញ {0}"],
  e_starts: [
    "Starts {0}",
    // new
    "ចាប់ផ្ដើម {0}",
  ],
  e_tg_linked: ["Telegram linked", "បានភ្ជាប់ Telegram"],
  e_tg_none: ["No Telegram", "គ្មាន Telegram"],
  e_back: [
    "Back to Employees",
    // new
    "ត្រឡប់ទៅបុគ្គលិក",
  ],
  e_details: ["Details", "ព័ត៌មានលម្អិត"],
  e_edit: [
    "Change details",
    // new
    "កែព័ត៌មាន",
  ],
  e_pay: ["Pay details", "ព័ត៌មានប្រាក់ខែ"],
  e_salary: ["Salary", "ប្រាក់ខែ"],
  e_method: ["Payment method", "វិធីបើកប្រាក់ខែ"],
  e_aba_name: [
    "ABA account name",
    // new
    "ឈ្មោះគណនី ABA",
  ],
  e_aba_number: [
    "ABA account number",
    // new
    "លេខគណនី ABA",
  ],
  e_id: ["ID number", "លេខអត្តសញ្ញាណប័ណ្ណ"],
  e_id_type: [
    "ID type",
    // new
    "ប្រភេទអត្តសញ្ញាណ",
  ],
  id_NATIONAL_ID: [
    "National ID card",
    // new
    "អត្តសញ្ញាណប័ណ្ណសញ្ជាតិខ្មែរ",
  ],
  id_PASSPORT: [
    "Passport",
    // new
    "លិខិតឆ្លងដែន",
  ],
  id_OTHER: ["Other", "ផ្សេងទៀត"],
  e_birth: [
    "Date of birth",
    // new
    "ថ្ងៃខែឆ្នាំកំណើត",
  ],
  e_hire_again: [
    "Rehire: this person worked here before",
    // new
    "ជួលម្តងទៀត៖ បុគ្គលនេះធ្លាប់ធ្វើការនៅទីនេះ",
  ],
  e_nssf: [
    "NSSF number",
    // new
    "លេខ ប.ស.ស",
  ],
  e_birth_place: [
    "Place of birth",
    // new
    "ទីកន្លែងកំណើត",
  ],
  e_address: [
    "Home address",
    // new
    "អាសយដ្ឋានផ្ទះ",
  ],
  e_pay_hidden: [
    "Only users with the See salaries permission can see salaries, payment details and ID numbers.",
    "តែអ្នកមានសិទ្ធិ មើលប្រាក់ខែ ទើបឃើញប្រាក់ខែ ការបើកប្រាក់ និងលេខអត្តសញ្ញាណ។",
  ],
  e_pay_later: [
    "A user with the See salaries permission adds the salary later.",
    "អ្នកមានសិទ្ធិ មើលប្រាក់ខែ បន្ថែមប្រាក់ខែពេលក្រោយ។",
  ],
  e_pay_first: [
    "The salary becomes the first entry in the employment history.",
    "ប្រាក់ខែជាបន្ទាត់ទីមួយនៃប្រវត្តិការងារ។",
  ],
  e_pay_none: [
    "No salary yet.",
    // new
    "មិនទាន់មានប្រាក់ខែ។",
  ],
  e_change_pay: [
    "Change salary",
    // new
    "ប្ដូរប្រាក់ខែ",
  ],
  e_change_id: [
    "Change ID details",
    // new
    "កែព័ត៌មានអត្តសញ្ញាណ",
  ],
  e_history: ["Employment history", "ប្រវត្តិការងារ"],
  e_history_note: [
    "Each change adds a new entry with its effective date and reason. Earlier entries are never overwritten.",
    "ការកែបន្ថែមបន្ទាត់ថ្មី ជាមួយថ្ងៃចាប់ផ្ដើម និងមូលហេតុ។ បន្ទាត់ចាស់មិនដែលត្រូវសរសេរជាន់ទេ។",
  ],
  ev_HIRED: ["Started", "ចាប់ផ្ដើមធ្វើការ"],
  ev_JOB_CHANGE: [
    "Job changed",
    // new
    "ប្ដូរការងារ",
  ],
  ev_SHIFT_CHANGE: [
    "Shift changed",
    // new
    "ប្ដូរវេន",
  ],
  ev_LEFT: ["Left", "បានចាកចេញ"],
  ev_PAY: [
    "Salary changed",
    // new
    "ប្រាក់ខែ",
  ],
  e_docs: ["Documents", "ឯកសារ"],
  e_docs_note: [
    "Files are kept. They are never deleted.",
    "ឯកសាររក្សាទុក។ មិនដែលត្រូវលុបទេ។",
  ],
  e_add_file: ["Add file", "បន្ថែមឯកសារ"],
  e_file: ["File", "ឯកសារ"],
  e_doc_title: [
    "Title",
    // new
    "ចំណងជើង",
  ],
  e_doc_kind: [
    "Type",
    // new
    "ប្រភេទ",
  ],
  dk_ID_CARD: ["ID card", "អត្តសញ្ញាណប័ណ្ណ"],
  dk_CONTRACT: [
    "Contract",
    // new
    "កិច្ចសន្យា",
  ],
  dk_CERTIFICATE: [
    "Certificate",
    // new
    "វិញ្ញាបនបត្រ",
  ],
  dk_OTHER: ["Other", "ផ្សេងទៀត"],
  e_doc_expires: [
    "Expires on",
    // new
    "ផុតកំណត់នៅ",
  ],
  e_doc_types: [
    "JPG, PNG or PDF, up to 20 MB.",
    // new
    "ឯកសារ JPG PNG ឬ PDF មិនលើស 20 MB។",
  ],
  e_doc_open: [
    "Open",
    // new
    "បើក",
  ],
  e_doc_remove: [
    "Remove",
    // new
    "ដកចេញ",
  ],
  e_doc_removed: [
    "{0} removed. The file is kept in the audit log.",
    // new
    "{0} ត្រូវដកចេញ។ ឯកសាររក្សាទុកក្នុងប្រវត្តិ។",
  ],
  e_doc_none: [
    "No documents.",
    // new
    "គ្មានឯកសារ។",
  ],
  e_added_thing: ["{0} added.", "{0} បានបន្ថែម។"],
  e_change: ["Change job or salary", "ប្ដូរការងារ ឬប្រាក់ខែ"],
  e_change_t: ["Change job or salary · {0}", "ប្ដូរការងារ ឬប្រាក់ខែ · {0}"],
  e_change_job_t: [
    "Change job or shift · {0}",
    // new
    "ប្ដូរការងារ ឬវេន · {0}",
  ],
  e_changed: [
    "{0}: employment history updated.",
    "{0}៖ បានបន្ថែមបន្ទាត់ប្រវត្តិថ្មី។",
  ],
  e_saved: ["{0} saved.", "{0} បានរក្សាទុក។"],
  e_set_end: ["Set end date", "កំណត់ថ្ងៃឈប់ការងារ"],
  e_set_end_t: ["Set end date · {0}", "កំណត់ថ្ងៃឈប់ការងារ · {0}"],
  e_end_note: [
    "On the end date the Telegram link is removed and the last salary is counted up to that day.",
    "នៅថ្ងៃបញ្ចប់ ការភ្ជាប់ Telegram ត្រូវដកចេញ ហើយប្រាក់ខែចុងក្រោយគិតដល់ថ្ងៃនោះ។",
  ],
  e_end_signin: [
    "App sign-in {0} turns off at the end of that day.",
    "គណនីចូលកម្មវិធី {0} បិទនៅចុងថ្ងៃនោះ។",
  ],
  e_leaves_on: ["{0} leaves on {1}.", "{0} ចាកចេញនៅ {1}។"],
  e_added: ["Employee {0} added.", "បានបន្ថែមបុគ្គលិក {0}។"],
  e_add_t: ["Add employee", "បន្ថែមបុគ្គលិក"],
  e_no_jobs: [
    "No job titles yet. Add them in Settings first.",
    // new
    "មិនទាន់មានឈ្មោះការងារ។ សូមបន្ថែមក្នុងការកំណត់ជាមុន។",
  ],
  e_telegram: [
    "Telegram",
    // new
    "Telegram",
  ],
  e_tg_id: [
    "Telegram user ID",
    // new
    "លេខសម្គាល់អ្នកប្រើ Telegram",
  ],
  e_tg_role: ["Report role", "តួនាទីរបាយការណ៍"],
  e_tg_since: [
    "Since {0}",
    // new
    "ចាប់ពី {0}",
  ],
  e_tg_unlink: ["Remove Telegram link", "ដកការភ្ជាប់ Telegram"],
  e_tg_unlinked: ["{0}: Telegram unlinked.", "{0}៖ បានផ្ដាច់ Telegram។"],
  e_tg_owner_only: [
    "Only the Owner can give the Authorizer role.",
    "តែម្ចាស់ទើបអាចផ្ដល់តួនាទីអ្នកអនុម័ត។",
  ],
  e_tg_linked_to: ["{0} is linked to Telegram.", "{0} បានភ្ជាប់ Telegram។"],

  // New staff from Telegram
  sr_title: ["New staff from Telegram", "បុគ្គលិកថ្មីពី Telegram"],
  sr_sub: [
    "People who pressed Start in the staff bot. Link each one to an employee.",
    "អ្នកដែលចុច Start ក្នុងបូតបុគ្គលិក។ ភ្ជាប់ម្នាក់ៗទៅបុគ្គលិក។",
  ],
  sr_asked: ["{0} ({1}) asked to join on {2}.", "{0} ({1}) បានស្នើចូលនៅ {2}។"],
  sr_link: ["Link", "ភ្ជាប់"],
  sr_link_t: ["Link {0}", "ភ្ជាប់ {0}"],
  sr_refuse: ["Refuse", "បដិសេធ"],
  sr_refuse_t: ["Refuse {0}", "បដិសេធ {0}"],
  sr_not_listed: [
    "Not in the list? Add the employee first.",
    "មិនមានក្នុងបញ្ជី? សូមបន្ថែមបុគ្គលិកជាមុន។",
  ],
  sr_roles: ["Select one or more.", "គូសមួយ ឬច្រើន។"],
  sr_refused: [
    "Telegram request from {0} refused.",
    "សំណើ Telegram ពី {0} ត្រូវបដិសេធ។",
  ],

  // Employee card
  c_title: ["Employee card", "កាតបុគ្គលិក"],
  c_note: [
    "A caretaker scans this card on the office phone or tablet when the employee has no phone. A half-body photo is taken each time.",
    "អ្នកថែទាំស្កេនកាតនេះលើទូរស័ព្ទ ឬថេប្លេតការិយាល័យ ពេលបុគ្គលិកគ្មានទូរស័ព្ទ។ រូបថតពាក់កណ្ដាលខ្លួនត្រូវថតរាល់ដង។",
  ],
  c_card: ["Card {0} · since {1}", "កាត {0} · ចាប់ពី {1}"],
  c_works: ["Active", "ដំណើរការ"],
  c_stopped: ["Deactivated", "ឈប់ប្រើ"],
  c_stopped_left: [
    "Deactivated on {0}, when the employee left.",
    "ឈប់ប្រើនៅ {0} ពេលបុគ្គលិកចាកចេញ។",
  ],
  c_none: [
    "No card yet.",
    // new
    "មិនទាន់មានកាត។",
  ],
  c_make: [
    "Create card",
    // new
    "បង្កើតកាត",
  ],
  c_replace: ["Replace card", "ប្ដូរកាត"],
  c_replace_t: ["Replace the card of {0}?", "ប្ដូរកាតរបស់ {0}?"],
  c_replace_note: [
    "Use this when a card is lost or broken. The old card's QR stops working at once. Print the new card and give it to the employee.",
    "ប្រើពេលកាតបាត់ ឬខូច។ QR នៃកាតចាស់ឈប់ដំណើរការភ្លាម។ បោះពុម្ពកាតថ្មី ហើយប្រគល់ឱ្យបុគ្គលិក។",
  ],
  c_old: ["Old cards", "កាតចាស់"],
  c_new_code: [
    "The new card's code is {0}. Print it now: it is shown only once.",
    // new
    "កូដកាតថ្មីគឺ {0}។ សូមបោះពុម្ពឥឡូវ៖ វាបង្ហាញតែម្ដងប៉ុណ្ណោះ។",
  ],

  // Salary loans
  l_title: ["Salary loans", "ប្រាក់កម្ចីប្រាក់ខែ"],
  l_sub: [
    "Money lent to staff, repaid from salary.",
    "ប្រាក់ឱ្យបុគ្គលិកខ្ចី សងវិញពីប្រាក់ខែ។",
  ],
  l_new: ["New salary loan", "ប្រាក់កម្ចីប្រាក់ខែថ្មី"],
  l_rule: [
    "Business rule: a loan can be up to {0} of one month's salary, with at most {1} open per employee. The Owner approves loans, and no one can approve their own request.",
    "ច្បាប់អាជីវកម្ម៖ យ៉ាងច្រើន {0} នៃប្រាក់ខែមួយខែ និងប្រាក់កម្ចីមិនទាន់សង {1} ក្នុងមួយនាក់។ ម្ចាស់អនុម័ត។ គ្មាននរណាអនុម័តសំណើខ្លួនឯងទេ។",
  ],
  l_none: [
    "No salary loans.",
    // new
    "គ្មានប្រាក់កម្ចីប្រាក់ខែ។",
  ],
  l_number: ["Loan no.", "ប្រាក់កម្ចី"],
  l_amount: [
    "Amount",
    // new
    "ចំនួន",
  ],
  l_limit: ["Limit", "កម្រិត"],
  l_repayment: ["Repayment", "ការសងវិញ"],
  l_left_owed: ["Balance", "នៅសល់"],
  l_next: ["In full from the next salary", "សងទាំងអស់ពីប្រាក់ខែបន្ទាប់"],
  l_each: ["{0} each month", "{0} រៀងរាល់ខែ"],
  l_monthly: [
    "Monthly installment (set by the Owner)",
    "ចំនួនរៀងរាល់ខែ (ម្ចាស់កំណត់)",
  ],
  l_monthly_amount: ["Monthly installment", "ចំនួនរៀងរាល់ខែ"],
  l_telegram: ["Requested via Telegram", "ស្នើក្នុង Telegram"],
  l_within: ["Within limit {0}", "ក្នុងកម្រិត {0}"],
  l_over: ["Over the limit {0}", "លើសកម្រិត {0}"],
  l_send: ["Send for approval", "ផ្ញើទៅម្ចាស់"],
  l_sent: ["Loan {0} sent to the Owner.", "ប្រាក់កម្ចី {0} បានផ្ញើទៅម្ចាស់។"],
  l_sent_for: [
    "Salary loan for {0} sent to the Owner.",
    // new
    "ប្រាក់កម្ចីប្រាក់ខែសម្រាប់ {0} បានផ្ញើទៅម្ចាស់។",
  ],
  l_approve_t: ["Approve loan {0}", "អនុម័តប្រាក់កម្ចី {0}"],
  l_borrows: [
    "{0} borrows {1}. Repayment: {2}.",
    "{0} ខ្ចី {1}។ ការសងវិញ៖ {2}។",
  ],
  l_approved: ["Loan {0} approved.", "ប្រាក់កម្ចី {0} បានអនុម័ត។"],
  l_refused: [
    "Loan {0} not approved.",
    // new
    "ប្រាក់កម្ចី {0} មិនបានអនុម័ត។",
  ],
  l_payout: ["Pay out", "បើកប្រាក់"],
  l_payout_t: ["Pay out loan {0}", "បើកប្រាក់កម្ចី {0}"],
  l_paid_out: [
    "Loan {0} paid out.",
    // new
    "ប្រាក់កម្ចី {0} បានបើក។",
  ],
  l_paid_on: [
    "Paid on",
    // new
    "បើកនៅ",
  ],
  l_payout_method: [
    "Paid from",
    // new
    "បើកពី",
  ],
  l_own: [
    "Your own request. Someone else approves.",
    // new
    "សំណើរបស់អ្នក។ អ្នកផ្សេងអនុម័ត។",
  ],
  l_owner_note: [
    "Owner's own loan: enter a reason",
    // new
    "ប្រាក់កម្ចីផ្ទាល់របស់ម្ចាស់៖ សរសេរមូលហេតុ",
  ],
  ls_WAITING: ["Pending approval", "រង់ចាំម្ចាស់"],
  ls_APPROVED: ["Approved, not paid out", "បានអនុម័ត មិនទាន់បើក"],
  ls_PAID_OUT: ["Paid out", "បានបើក"],
  ls_REPAID: ["Repaid", "បានសងរួច"],
  ls_REFUSED: ["Rejected", "មិនបានអនុម័ត"],
  approve: ["Approve", "អនុម័ត"],
  refuse: ["Refuse", "បដិសេធ"],

  // Payroll
  p_title: ["Payroll", "បញ្ជីប្រាក់ខែ"],
  p_sub: [
    "Each month's salaries, checked, approved and paid on pay day.",
    "ប្រាក់ខែប្រចាំខែ ពិនិត្យ អនុម័ត និងបើកនៅថ្ងៃបើកប្រាក់ខែ។",
  ],
  p_rule: [
    "Business rule: salaries are paid on day {0} of the next month. The app prepares payroll on the 1st, the Accountant reviews it by the 3rd and the Owner approves it by the 4th. The month cannot be closed until payroll is approved.",
    "ច្បាប់អាជីវកម្ម៖ ប្រាក់ខែបើកនៅថ្ងៃទី {0} នៃខែបន្ទាប់។ កម្មវិធីបង្កើតបញ្ជីនៅថ្ងៃទី១ គណនេយ្យករពិនិត្យមុនថ្ងៃទី៣ ម្ចាស់អនុម័តមុនថ្ងៃទី៤។ មិនអាចបិទខែបានទេ រហូតបញ្ជីប្រាក់ខែត្រូវអនុម័ត។",
  ],
  p_tax_off: [
    "Salary tax and NSSF deductions are turned off until a tax agent confirms the amounts.",
    "ពន្ធលើប្រាក់បៀវត្ស និង ប.ស.ស បិទរហូតភ្នាក់ងារពន្ធបញ្ជាក់ចំនួន។",
  ],
  p_make: [
    "Create payroll for {0}",
    // new
    "បង្កើតបញ្ជីសម្រាប់ {0}",
  ],
  p_none: ["No payroll for this month.", "គ្មានបញ្ជីប្រាក់ខែសម្រាប់ខែនេះ។"],
  p_period: ["Pay period", "រយៈពេលប្រាក់ខែ"],
  p_for: ["Salaries for {0}", "ប្រាក់ខែ {0}"],
  p_pay_on: ["Pay on {0}", "បើកនៅ {0}"],
  p_net: ["Net pay", "ប្រាក់ខែសុទ្ធ"],
  p_people: [
    "Employees",
    // new
    "មនុស្ស",
  ],
  p_back: [
    "Back to Payroll",
    // new
    "ត្រឡប់ទៅបញ្ជីប្រាក់ខែ",
  ],
  p_correction: [
    "Correction",
    // new
    "ការកែតម្រូវ",
  ],
  p_make_correction: [
    "Create correction payroll",
    // new
    "បង្កើតបញ្ជីកែតម្រូវ",
  ],
  p_correction_note: [
    "An approved payroll cannot be changed. A correction payroll adds anything that was missed, with its own journal entry.",
    // new
    "បញ្ជីដែលបានអនុម័តមិនផ្លាស់ប្ដូរទេ។ បញ្ជីកែតម្រូវបន្ថែមអ្វីដែលខ្វះ ជាមួយធាតុរបស់វា។",
  ],
  ps_LIST_MADE: ["Prepared", "បានរៀបចំ"],
  ps_SENT_FOR_APPROVAL: ["Reviewed", "បានពិនិត្យ"],
  ps_SENT_BACK: [
    "Sent back",
    // new
    "បានផ្ញើត្រឡប់",
  ],
  ps_APPROVED: ["Approved", "បានអនុម័ត"],
  ps_PAID: ["Paid", "បានបើក"],
  p_being_checked: ["In review", "កំពុងពិនិត្យ"],
  p_days_worked: ["Days worked", "ថ្ងៃធ្វើការ"],
  p_lines: ["Earnings and deductions", "ប្រាក់បន្ថែម និងប្រាក់កាត់"],
  p_loan: ["Loan repayment", "ការសងប្រាក់កម្ចី"],
  p_add_line: ["Add item", "បន្ថែមបន្ទាត់"],
  p_line_added: ["Line added.", "បានបន្ថែមបន្ទាត់។"],
  p_line_removed: [
    "Line removed.",
    // new
    "បានដកបន្ទាត់។",
  ],
  p_remove_line: [
    "Remove line",
    // new
    "ដកបន្ទាត់",
  ],
  p_component: [
    "Type",
    // new
    "បន្ទាត់",
  ],
  p_from_att: ["From attendance", "ពីវត្តមាន"],
  p_clock_note: [
    "Lines marked with a clock come from Attendance.",
    "បន្ទាត់ដែលមានរូបនាឡិកា មកពីវត្តមាន។",
  ],
  p_send: ["Send for approval", "ផ្ញើទៅម្ចាស់"],
  p_sent: ["Sent to the Owner.", "បានផ្ញើទៅម្ចាស់។"],
  p_send_back: [
    "Send back",
    // new
    "ផ្ញើត្រឡប់",
  ],
  p_sent_back: ["Sent back to the Accountant.", "បានផ្ញើត្រឡប់ទៅគណនេយ្យករ។"],
  p_approve: ["Approve payroll", "អនុម័តបញ្ជីប្រាក់ខែ"],
  p_approve_t: ["Approve payroll {0}", "អនុម័តបញ្ជីប្រាក់ខែ {0}"],
  p_approve_note: [
    "Employees: {0}. Total to pay: {1}. One journal entry per employee is posted, dated {2}.",
    "{0} នាក់ ត្រូវបើក {1}។ ធាតុមួយក្នុងមួយនាក់ចូលសៀវភៅ ចុះថ្ងៃ {2}។",
  ],
  p_own_checked: [
    "You also reviewed this payroll. This is recorded in the audit log.",
    "អ្នកក៏បានពិនិត្យបញ្ជីនេះដែរ។ កំណត់សម្គាល់ត្រូវរក្សាទុក។",
  ],
  p_approved: ["Payroll {0} approved.", "បញ្ជីប្រាក់ខែ {0} បានអនុម័ត។"],
  p_pay_list: ["Payment list for {0}", "បញ្ជីបើកប្រាក់សម្រាប់ {0}"],
  p_pay_note: [
    "Pay from the joint ABA account (or in cash), then mark each employee as paid.",
    "បើកពីគណនី ABA រួម (ឬសាច់ប្រាក់) រួចគូសម្នាក់ៗ។",
  ],
  p_mark_paid: ["Mark paid", "គូសថាបានបើក"],
  p_mark_paid_t: ["Mark paid · {0}", "គូសថាបានបើក · {0}"],
  p_to: ["{0} to {1}.", "{0} ទៅ {1}។"],
  p_paid: ["Paid {0}", "បានបើក {0}"],
  p_marked: ["{0} marked paid.", "{0} បានគូសថាបានបើក។"],
  p_not_paid: ["Not paid yet", "មិនទាន់បើក"],
  p_not_paid_n: ["Not yet marked paid: {0}", "{0} នាក់មិនទាន់គូសថាបានបើក"],
  p_bank_ref: [
    "ABA reference",
    // new
    "លេខយោង ABA",
  ],
  p_reverse: [
    "Reverse payment",
    // new
    "បញ្ច្រាសការបើក",
  ],
  p_reverse_t: [
    "Reverse the payment to {0}?",
    // new
    "បញ្ច្រាសការបើកប្រាក់ឱ្យ {0}?",
  ],
  p_reverse_note: [
    "A reversing journal entry is posted. The original payment record is kept.",
    // new
    "ធាតុបញ្ច្រាសចូលសៀវភៅ។ បន្ទាត់ការបើកនៅដដែល។",
  ],
  p_reversed: [
    "Payment to {0} reversed.",
    // new
    "ការបើកប្រាក់ឱ្យ {0} ត្រូវបញ្ច្រាស។",
  ],
  p_payslip: ["Payslip", "បង្កាន់ដៃប្រាក់ខែ"],
  p_payslip_t: ["Payslip · {0} · {1}", "បង្កាន់ដៃប្រាក់ខែ · {0} · {1}"],
  p_payslip_bot: [
    "In a later update, payslips will also be sent through the staff Telegram bot.",
    "ពេលក្រោយ បង្កាន់ដៃប្រាក់ខែក៏ផ្ញើក្នុងបូតបុគ្គលិកដែរ។",
  ],
  p_earnings: [
    "Earnings",
    // new
    "ប្រាក់ចំណូល",
  ],
  p_deductions: [
    "Deductions",
    // new
    "ប្រាក់កាត់",
  ],
  p_amount: ["Amount", "ចំនួន"],
  pc_BASE_SALARY: ["Base salary", "ប្រាក់ខែប្រចាំខែ"],
  pc_BONUS: [
    "Bonus",
    // new
    "ប្រាក់រង្វាន់",
  ],
  pc_OTHER_PLUS: [
    "Other addition",
    // new
    "ប្រាក់បន្ថែមផ្សេងៗ",
  ],
  pc_OTHER_MINUS: [
    "Other deduction",
    // new
    "ប្រាក់កាត់ផ្សេងៗ",
  ],
  pc_OVERTIME: ["Overtime", "ម៉ោងបន្ថែម"],
  pc_DAYS_NOT_WORKED: [
    "Days not worked",
    // new
    "ថ្ងៃមិនបានធ្វើការ",
  ],
  pc_LOAN_REPAYMENT: ["Loan repayment", "ការសងប្រាក់កម្ចី"],
  p_locked_month: [
    "{0} is locked because its payroll was sent for approval. Attendance can no longer be corrected.",
    "{0} ត្រូវចាក់សោ៖ បញ្ជីប្រាក់ខែបានផ្ញើសុំអនុម័ត។ មិនអាចកែបានទេ។",
  ],

  // Attendance
  a_title: ["Attendance", "វត្តមាន"],
  a_sub: [
    "Shifts worked, lateness, absences, leave and pre-approved overtime.",
    "អ្នកណាធ្វើវេនណា យឺត អវត្តមាន ឬឈប់សម្រាក និងម៉ោងបន្ថែមដែលអនុម័តមុនធ្វើការ។",
  ],
  a_day: ["Daily sheet", "តារាងប្រចាំថ្ងៃ"],
  a_week: ["Weekly plan", "ផែនការប្រចាំសប្ដាហ៍"],
  a_ot: ["Overtime", "ម៉ោងបន្ថែម"],
  a_month: ["Month summary", "សង្ខេបប្រចាំខែ"],
  a_places: ["QR locations", "ទីតាំង QR"],
  a_day_before: ["Previous day", "ថ្ងៃមុន"],
  a_next_day: ["Next day", "ថ្ងៃបន្ទាប់"],
  a_today: ["today", "ថ្ងៃនេះ"],
  a_all_shifts: ["All shifts", "វេនទាំងអស់"],
  a_shift: ["Shift", "វេន"],
  a_in: ["Clock-in", "ចូល"],
  a_out: ["Clock-out", "ចេញ"],
  a_status: [
    "Status",
    // new
    "ស្ថានភាព",
  ],
  a_on_shift: ["On shift", "កំពុងនៅវេន"],
  a_present: ["Present", "មានវត្តមាន"],
  a_late: ["Late {0} min", "យឺត {0} នាទី"],
  a_not_started: ["Shift not started", "វេនមិនទាន់ចាប់ផ្ដើម"],
  a_no_in: ["No clock-in", "គ្មានការចុះចូល"],
  a_no_out: ["No clock-out", "គ្មានការចុះចេញ"],
  st_WORKED: ["Worked", "បានធ្វើការ"],
  st_ABSENT: ["Absent", "អវត្តមាន"],
  st_LEAVE_ANNUAL: ["Annual leave", "ច្បាប់ប្រចាំឆ្នាំ"],
  st_LEAVE_SICK: ["Sick leave", "ច្បាប់ឈឺ"],
  st_LEAVE_UNPAID: ["Unpaid leave", "ច្បាប់គ្មានប្រាក់ខែ"],
  st_DAY_OFF: ["Day off", "ថ្ងៃឈប់"],
  a_edit: ["Edit times", "កែម៉ោង"],
  a_edit_t: [
    "Edit times · {0} · {1}",
    // new
    "កែម៉ោង · {0} · {1}",
  ],
  a_fixed: ["Corrected by {0}, {1}: {2}", "កែដោយ {0} {1}៖ {2}"],
  a_fixed_short: [
    "Corrected: {0}",
    // new
    "បានកែ៖ {0}",
  ],
  a_worked_note: [
    "For Worked, the app shows Present or Late based on the clock-in time.",
    "សម្រាប់ បានធ្វើការ កម្មវិធីបង្ហាញ មានវត្តមាន ឬយឺត តាមម៉ោងចូល។",
  ],
  a_old_kept: [
    "The original times are kept. The correction and reason are recorded in the audit log.",
    "ម៉ោងចាស់ត្រូវរក្សាទុក។ ការកែ និងមូលហេតុចូលក្នុងប្រវត្តិ។",
  ],
  a_saved: ["Attendance corrected for {0}.", "បានកែវត្តមានសម្រាប់ {0}។"],
  a_nobody: [
    "No one is scheduled for this shift on this day.",
    "គ្មាននរណាម្នាក់នៅវេននេះក្នុងថ្ងៃនេះទេ។",
  ],
  a_night_note: [
    "A night shift is counted on the day it starts.",
    // new (cut from the approved sentence)
    "វេនយប់ជារបស់ថ្ងៃដែលវាចាប់ផ្ដើម។",
  ],
  a_locked: ["Locked", "ចាក់សោ"],
  a_how: [
    "How each time was recorded: Phone = the employee scanned the location QR code. Card = a caretaker scanned the employee card and took a photo. Manual = entered or corrected in the app, with a reason.",
    // new (shorter than the approved sentence)
    "របៀបដែលម៉ោងនីមួយៗចូលមក៖ ទូរស័ព្ទ = បុគ្គលិកស្កេន QR ទីតាំង។ កាត = អ្នកថែទាំស្កេនកាតបុគ្គលិក ហើយថតរូប។ បញ្ចូលដោយដៃ = បញ្ចូល ឬកែក្នុងកម្មវិធី មានមូលហេតុ។",
  ],
  src_QR_PHONE: [
    "Phone",
    // new
    "ទូរស័ព្ទ",
  ],
  src_QR_CARD: ["Card", "កាត"],
  src_MANUAL: ["Manual", "បញ្ចូលដោយដៃ"],
  a_needs_check: ["Needs review", "ត្រូវពិនិត្យ"],
  a_accept: ["Accept", "ទទួលយក"],
  a_accepted: ["Accepted: {0}, {1}.", "បានទទួលយក៖ {0} {1}។"],
  a_accepted_chip: [
    "Accepted",
    // new
    "បានទទួលយក",
  ],
  a_accept_t: [
    "Accept the scan of {0}?",
    // new
    "ទទួលយកការស្កេនរបស់ {0}?",
  ],
  a_accept_note: [
    "No pay is deducted. Enter the correct time if you know it.",
    "មិនកាត់ប្រាក់ខែ។ បញ្ចូលម៉ោងតាមអ្វីដែលអ្នកដឹង។",
  ],
  a_distance: ["{0} m", "{0} ម"],
  a_scanned_by: ["scanned by {0}", "ស្កេនដោយ {0}"],
  a_photo: ["Card photo · {0}", "រូបថតកាត · {0}"],
  a_open_photo: [
    "Open card photo",
    // new
    "បើករូបថតកាត",
  ],
  cr_NO_PHONE: ["No phone", "គ្មានទូរស័ព្ទ"],
  cr_PHONE_BROKEN: ["Phone broken", "ទូរស័ព្ទខូច"],
  cr_PHONE_LOST: ["Phone lost", "ទូរស័ព្ទបាត់"],
  cr_PHONE_STOLEN: ["Phone stolen", "ទូរស័ព្ទត្រូវគេលួច"],
  cr_OTHER: ["Other", "ផ្សេងទៀត"],
  a_week_before: ["Previous week", "សប្ដាហ៍មុន"],
  a_next_week: ["Next week", "សប្ដាហ៍ក្រោយ"],
  a_off: ["Day off", "ឈប់"],
  a_days_off: ["Days off", "ថ្ងៃឈប់"],
  a_fewer_off: ["Too few days off (minimum {0})", "តិចជាង {0} ថ្ងៃឈប់"],
  a_month_off: [
    "{0}: {1} of {2} days off",
    // new
    "{0}៖ ឈប់ {1} ក្នុងចំណោម {2} ថ្ងៃ",
  ],
  a_past_note: [
    "Past days cannot be changed. An employee with fewer days off than the weekly minimum ({0}) gets a warning, but the plan can still be saved.",
    "ថ្ងៃកន្លងហើយមិនអាចប្ដូរ។ អ្នកមានថ្ងៃឈប់តិចជាង {0} ក្នុងសប្ដាហ៍ ទទួលការព្រមាន វាមិនបញ្ឈប់ផែនការទេ។",
  ],
  a_plan_saved: ["Plan saved.", "បានរក្សាទុកផែនការ។"],
  a_plan_t: [
    "Plan · {0} · {1}",
    // new
    "ផែនការ · {0} · {1}",
  ],
  a_not_working: [
    "Not working",
    // new
    "មិនធ្វើការ",
  ],
  ot_title: ["Overtime approvals", "ការអនុម័តម៉ោងបន្ថែម"],
  ot_request: ["Request overtime", "ស្នើម៉ោងបន្ថែម"],
  ot_send: ["Send for approval", "ផ្ញើសុំអនុម័ត"],
  ot_ask_note: [
    "Request overtime before the work starts. Overtime worked without approval is not paid.",
    "សុំមុនធ្វើការ។ ម៉ោងធ្វើដោយគ្មានការអនុម័តមិនត្រូវបង់ទេ។",
  ],
  ot_sent: [
    "Overtime {0} sent for approval.",
    "បានផ្ញើម៉ោងបន្ថែម {0} សុំអនុម័ត។",
  ],
  ot_sent_for: [
    "Overtime for {0} sent for approval.",
    // new
    "បានផ្ញើម៉ោងបន្ថែមសម្រាប់ {0} សុំអនុម័ត។",
  ],
  ot_from: ["From", "ពី"],
  ot_to: ["To", "ដល់"],
  ot_when: ["Date", "ពេល"],
  ot_hours: ["Hours", "ម៉ោង"],
  ot_h: ["{0} h", "{0} ម៉"],
  ot_night_h: [
    "{0} h night",
    // new
    "{0} ម៉ យប់",
  ],
  ot_asked: ["Requested by {0}, {1}", "សុំដោយ {0} {1}"],
  ot_waiting: ["Pending", "កំពុងរង់ចាំ"],
  ot_refused: ["Refused", "បានបដិសេធ"],
  ot_approved_chip: ["Approved", "បានអនុម័ត"],
  ot_own: [
    "You asked for this. Someone else approves.",
    "អ្នកជាអ្នកសុំ។ អ្នកផ្សេងអនុម័ត។",
  ],
  ot_approved: [
    "Overtime {0} approved for {1}.",
    "បានអនុម័តម៉ោងបន្ថែម {0} សម្រាប់ {1}។",
  ],
  ot_refused_msg: [
    "Overtime {0} refused for {1}.",
    // new (shorter than the approved sentence)
    "បានបដិសេធម៉ោងបន្ថែម {0} សម្រាប់ {1}។",
  ],
  ot_refuse_t: ["Refuse {0}", "បដិសេធ {0}"],
  ot_none: ["None.", "គ្មាន។"],
  m_title: ["Attendance for {0}", "វត្តមានសម្រាប់ {0}"],
  m_locked: [
    "Locked: this month's payroll was sent for approval.",
    // new (shorter than the approved sentence)
    "ចាក់សោ៖ បញ្ជីប្រាក់ខែខែនេះបានផ្ញើសុំអនុម័ត។",
  ],
  m_worked: ["Worked", "ធ្វើការ"],
  m_late: ["Late", "យឺត"],
  m_absent: ["Absent", "អវត្តមាន"],
  m_leave: ["Leave", "ច្បាប់"],
  m_ot: ["OT {0}", "ម.ប {0}"],
  m_note: [
    "Worked, Late and Absent show the number of days in the month. OT = pre-approved overtime hours.",
    "ធ្វើការ យឺត និងអវត្តមាន រាប់ថ្ងៃក្នុងខែ។ ម.ប = ម៉ោងបន្ថែមដែលអនុម័តមុនធ្វើការ។",
  ],
  m_no_entry: [
    "No entry",
    // new
    "គ្មានការបញ្ចូល",
  ],
  m_month: [
    "Month",
    // new
    "ខែ",
  ],
  q_note: [
    "Staff clock in and out by scanning the QR code at a location. The phone must be within {0} of the map pin.",
    // new (shorter than the approved sentence)
    "បុគ្គលិកចុះចូល និងចុះចេញ ដោយស្កេន QR នៅទីតាំង។ ទូរស័ព្ទត្រូវនៅក្នុង {0} ពីចំណុចផែនទី។",
  ],
  q_metres: ["{0} metres", "{0} ម៉ែត្រ"],
  q_place: ["Location", "ទីតាំង"],
  q_pin: ["Map pin", "ចំណុចផែនទី"],
  q_no_pin: [
    "No map pin: every scan here needs review.",
    // new
    "គ្មានចំណុច៖ ការស្កេននៅទីនេះត្រូវពិនិត្យទាំងអស់។",
  ],
  q_set_pin: [
    "Set pin",
    // new
    "កំណត់ចំណុច",
  ],
  q_set_pin_t: [
    "Map pin · {0}",
    // new
    "ចំណុចផែនទី · {0}",
  ],
  q_pin_help: [
    "Enter the coordinates, for example 11.6045, 104.8902 (in Google Maps, press and hold the location).",
    "វាយចំណុចដូចជា 11.6045, 104.8902 (ពី Google Maps៖ ចុចជាប់លើទីតាំង)។",
  ],
  q_pin_bad: [
    "Enter two numbers separated by a comma, for example 11.6045, 104.8902.",
    "វាយលេខពីរ មានក្បៀស ដូចជា 11.6045, 104.8902។",
  ],
  q_pin_saved: [
    "Pin saved for {0}.",
    // new
    "បានរក្សាទុកចំណុចសម្រាប់ {0}។",
  ],
  q_in_use: ["QR in use", "QR កំពុងប្រើ"],
  q_since: ["{0} · since {1}", "{0} · ចាប់ពី {1}"],
  q_no_qr: [
    "No QR yet.",
    // new
    "មិនទាន់មាន QR។",
  ],
  q_make: [
    "Create QR code",
    // new
    "បង្កើត QR",
  ],
  q_replace: ["Replace QR", "ប្ដូរ QR"],
  q_replace_t: ["Replace the QR at {0}?", "ប្ដូរ QR នៅ {0}?"],
  q_replace_note: [
    "The old QR stops working at once. Print the new QR and put it up before the next shift.",
    // new (shorter than the approved sentence)
    "QR ចាស់ឈប់ដំណើរការភ្លាម។ បោះពុម្ព QR ថ្មី ហើយបិទមុនវេនបន្ទាប់។",
  ],
  q_new_code: [
    "{0}: the new QR code is {1}. Print it now: it is shown only once.",
    // new
    "{0}៖ កូដ QR ថ្មីគឺ {1}។ សូមបោះពុម្ពឥឡូវ៖ វាបង្ហាញតែម្ដងប៉ុណ្ណោះ។",
  ],
  q_owner_only: [
    "Only the Owner sets pins and QR codes.",
    // new
    "មានតែម្ចាស់ទេ ដែលកំណត់ចំណុច និងកូដ QR។",
  ],
  q_none: [
    "No QR locations yet.",
    // new
    "មិនទាន់មានទីតាំង QR។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type HrTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function ht(
  language: Language,
  key: HrTextKey,
  ...values: (string | number)[]
): string {
  const words: string = TEXT[key][language === "km" ? 1 : 0];
  return singular(
    words.replace(/\{(\d+)\}/g, (match, index: string) => {
      const value = values[Number(index)];
      return value === undefined ? match : String(value);
    }),
  );
}

/** Words for a code such as a shift, a status or a line kind; the code itself when unknown. */
export function codeText(
  language: Language,
  prefix: string,
  code: string,
): string {
  const key = `${prefix}${code}`;
  return key in TEXT ? ht(language, key as HrTextKey) : code;
}
