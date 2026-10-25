// V1-058 R4: the words of the Utilities screens in English and Khmer, from the owner's
// mock-up (i18n.js, app.js). Khmer needs the native check before the app is used. Lines
// marked "new" are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  sub: ["Meter readings and meters", "អំណាន និងនាឡិកាស្ទង់"],
  tab_read: ["Meter readings", "អំណាននាឡិកាស្ទង់"],
  tab_meters: ["Meters", "នាឡិកាស្ទង់"],
  // new
  loading: ["Loading the meters…", "កំពុងផ្ទុកនាឡិកាស្ទង់…"],
  // new
  failed: [
    "The meters could not be read just now. Check the connection and try again.",
    "មិនអាចអាននាឡិកាស្ទង់បានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  // new
  failed_units: [
    "The meters of {0} could not be read. Try again.",
    "មិនអាចអាននាឡិកាស្ទង់របស់ {0} បានទេ។ សូមព្យាយាមម្តងទៀត។",
  ],
  unit: ["Unit", "បន្ទប់"],
  all_units: ["All Units", "គ្រប់បន្ទប់"],
  unit_bad: [
    'No Unit "{0}". Type a Unit number such as {1}, or clear the box to see all Units.',
    'គ្មានបន្ទប់ "{0}"។ វាយលេខបន្ទប់ដូចជា {1} ឬលុបប្រអប់ ដើម្បីមើលគ្រប់បន្ទប់។',
  ],
  period: ["Month", "ខែ"],
  p_all: ["All", "ទាំងអស់"],
  p_month: ["This month", "ខែនេះ"],
  p_six: ["6 months", "6 ខែ"],
  p_pick: ["Pick a month", "ជ្រើសខែ"],
  meter_kind: ["Meter", "នាឡិកាស្ទង់"],
  ELECTRICITY: ["Electricity", "អគ្គិសនី"],
  WATER: ["Water", "ទឹក"],
  floor_all: ["All floors", "គ្រប់ជាន់"],
  floor_n: ["Floor {0}", "ជាន់ទី {0}"],
  only_missing: ["Only not read", "តែមិនទាន់អាន"],
  progress: ["{0} of {1} meters read", "បានអាន {0} ក្នុងចំណោម {1}"],
  // new (the mock-up names the date in the words)
  next_inv: [
    "Read every meter, including empty rooms. Invoices are made on {0} from these readings.",
    "អានគ្រប់នាឡិកាស្ទង់ រួមទាំងបន្ទប់ទំនេរ។ វិក្កយបត្រនឹងចេញថ្ងៃ {0} ពីអំណានទាំងនេះ។",
  ],
  all_done: [
    "All meters are read. Invoices will be made on the 25th.",
    "បានអានគ្រប់នាឡិកាស្ទង់។ វិក្កយបត្រនឹងចេញនៅថ្ងៃទី 25។",
  ],
  // new
  none_left: [
    "Every meter on this list is read.",
    "នាឡិកាស្ទង់ទាំងអស់ក្នុងបញ្ជីនេះបានអានរួច។",
  ],
  // new
  no_meters: [
    "No meters yet. Add them on the Meters tab.",
    "មិនទាន់មាននាឡិកាស្ទង់។ សូមបន្ថែមនៅផ្ទាំងនាឡិកាស្ទង់។",
  ],
  // new
  before_day: [
    "Reading day is {0}. The list to type the readings opens that day.",
    "ថ្ងៃអានគឺ {0}។ បញ្ជីសម្រាប់វាយអំណានបើកនៅថ្ងៃនោះ។",
  ],
  col_unit_meter: ["Unit · Meter", "បន្ទប់ · នាឡិកាស្ទង់"],
  col_last: ["Last reading", "អំណានចុងក្រោយ"],
  col_new: ["New reading", "អំណានថ្មី"],
  col_used: ["Used", "បានប្រើ"],
  col_result: ["Result", "លទ្ធផល"],
  save: ["Save", "រក្សាទុក"],
  saved: ["Saved", "បានរក្សាទុក"],
  // new
  saved_on: ["Saved {0}", "បានរក្សាទុក {0}"],
  not_read: ["Not read yet", "មិនទាន់អាន"],
  typed: ["Not saved yet", "មិនទាន់រក្សាទុក"],
  // new
  no_last: ["No reading yet", "មិនទាន់មានអំណាន"],
  vacant_note: ["Vacant. The Property pays.", "ទំនេរ។ អគារជាអ្នកបង់។"],
  reserved_note: ["Reserved. No Lease yet.", "បានកក់។ មិនទាន់មានកិច្ចសន្យា។"],
  // new
  other_note: ["No Lease now.", "គ្មានកិច្ចសន្យាឥឡូវនេះ។"],
  err_num: ["Enter whole numbers only.", "សូមបញ្ចូលតែលេខគត់។"],
  // changed: V1 has no "report broken" yet, so a Manager replaces the meter.
  err_lower: [
    "Lower than the last reading ({0}). Check the meter. If it is broken, a Manager replaces it on the Meters tab.",
    "ទាបជាងអំណានចុងក្រោយ ({0})។ សូមពិនិត្យនាឡិកាស្ទង់។ បើវាខូច អ្នកគ្រប់គ្រងប្តូរវានៅផ្ទាំងនាឡិកាស្ទង់។",
  ],
  warn_high: [
    "{0} is much more than usual (about {1}). Check the meter, then save again.",
    "{0} ច្រើនជាងធម្មតា (ប្រហែល {1})។ សូមពិនិត្យ រួចរក្សាទុកម្តងទៀត។",
  ],
  save_anyway: ["Save anyway", "រក្សាទុកដដែល"],
  broken: ["Broken", "ខូច"],
  rd_broken: [
    "A broken meter cannot be read. Replace it first.",
    "នាឡិកាស្ទង់ខូចមិនអាចអានបាន។ សូមប្តូរវាជាមុន។",
  ],
  replace: ["Replace meter", "ប្តូរនាឡិកាស្ទង់"],
  // new
  done_one: ["{0}: saved.", "{0}៖ បានរក្សាទុក។"],
  // new
  conflict: [
    "This meter changed while you were typing, so the list was read again. Check the reading and save again.",
    "នាឡិកាស្ទង់នេះបានផ្លាស់ប្តូរ ពេលអ្នកកំពុងវាយ ដូច្នេះបញ្ជីត្រូវបានអានម្តងទៀត។ សូមពិនិត្យអំណាន ហើយរក្សាទុកម្តងទៀត។",
  ],
  // new
  save_failed: [
    "The reading was not saved. Check the connection and try again.",
    "អំណានមិនត្រូវបានរក្សាទុកទេ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  refused: [
    "The reading was refused. It may be lower than a reading already saved, or dated before the meter was put in.",
    "អំណានត្រូវបានបដិសេធ។ វាអាចទាបជាងអំណានដែលបានរក្សាទុករួច ឬមុនថ្ងៃដាក់នាឡិកាស្ទង់។",
  ],
  // new
  not_allowed_save: [
    "You may see the readings but not save them.",
    "អ្នកអាចមើលអំណាន ប៉ុន្តែមិនអាចរក្សាទុកបានទេ។",
  ],
  rd_day: ["Reading day", "ថ្ងៃអាន"],
  rd_reading: ["Reading", "អំណាន"],
  rd_note: ["Note", "កំណត់ចំណាំ"],
  rd_none_m: ["No readings in {0}.", "គ្មានអំណានក្នុងខែ{0}។"],
  // new
  rd_none: ["No readings yet.", "មិនទាន់មានអំណាន។"],
  rd_grid_note: [
    "Each box shows the reading and, under it, the use since the reading before, in {0}.",
    "ប្រអប់នីមួយៗបង្ហាញអំណាន ហើយខាងក្រោមជាការប្រើតាំងពីអំណានមុន គិតជា {0}។",
  ],
  rd_n_new: [
    "New meter put in. First reading.",
    "ដាក់នាឡិកាស្ទង់ថ្មី។ អំណានដំបូង។",
  ],
  // new
  rd_corrected: ["Corrected from {0}.", "បានកែពី {0}។"],
  // new
  records: ["Earlier forms", "ទម្រង់មុន"],
  // new
  records_note: [
    "Meters, rates, corrections and move-in or move-out readings, in English, until the next steps move them into this screen.",
    "នាឡិកាស្ទង់ អត្រា ការកែ និងអំណានពេលចូល ឬចេញ ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ផ្លាស់វាមកអេក្រង់នេះ។",
  ],
  // R4b Meters
  mt_c_el: ["Electricity meters", "នាឡិកាស្ទង់អគ្គិសនី"],
  mt_c_wa: ["Water meters", "នាឡិកាស្ទង់ទឹក"],
  mt_c_inuse: ["In use, one per Unit", "កំពុងប្រើ មួយក្នុងមួយបន្ទប់"],
  mt_c_nbroken: ["{0} broken", "ខូច {0}"],
  mt_c_allok: ["All working", "ដំណើរការទាំងអស់"],
  mt_c_broken: ["Broken meters", "នាឡិកាស្ទង់ខូច"],
  mt_c_before: ["Replace before {0}", "ប្តូរមុនថ្ងៃ {0}"],
  // new
  mt_c_none: ["None broken", "គ្មានខូច"],
  mt_f_all: ["All meters", "នាឡិកាស្ទង់ទាំងអស់"],
  mt_f_working: ["Working", "ដំណើរការ"],
  mt_f_broken: ["Broken", "ខូច"],
  mt_f_replaced: ["Replaced (history)", "បានប្តូរ (ប្រវត្តិ)"],
  mt_st_ok: ["Working", "ដំណើរការ"],
  mt_broken_since: ["Broken since {0}", "ខូចតាំងពី {0}"],
  mt_replaced_on: ["Replaced {0}", "បានប្តូរ {0}"],
  col_type: ["Type", "ប្រភេទ"],
  col_status: ["Status", "ស្ថានភាព"],
  mt_installed: ["Put in on", "ដាក់ថ្ងៃ"],
  mt_last: ["Last reading", "អំណានចុងក្រោយ"],
  mt_showing: ["{0} meters", "នាឡិកាស្ទង់ {0}"],
  mt_none: [
    "No meters match these filters.",
    "គ្មាននាឡិកាស្ទង់ត្រូវនឹងតម្រងនេះទេ។",
  ],
  ic_showing: ["Showing: {0}.", "កំពុងបង្ហាញ៖ {0}។"],
  pc_clear: ["Show all", "បង្ហាញទាំងអស់"],
  mt_add: ["Add meter", "បន្ថែមនាឡិកាស្ទង់"],
  manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  mt_add_intro: [
    "For a Unit that has no meter of this kind, such as a new Unit. A Unit has one electricity meter and one water meter. To change a broken meter, open it and choose Replace meter.",
    "សម្រាប់បន្ទប់ដែលគ្មាននាឡិកាស្ទង់ប្រភេទនេះ ដូចជាបន្ទប់ថ្មី។ បន្ទប់មួយមាននាឡិកាស្ទង់អគ្គិសនីមួយ និងទឹកមួយ។ ដើម្បីប្តូរនាឡិកាស្ទង់ខូច សូមបើកវា ហើយជ្រើស ប្តូរនាឡិកាស្ទង់។",
  ],
  mt_e_unit: ["Choose a Unit.", "សូមជ្រើសបន្ទប់។"],
  // new
  mt_pick_unit: ["Choose a Unit", "ជ្រើសបន្ទប់"],
  mt_e_have: [
    "{0} already has a working {1} meter ({2}). A Unit can have only one.",
    "{0} មាននាឡិកាស្ទង់{1}កំពុងប្រើរួចហើយ ({2})។ បន្ទប់មួយអាចមានតែមួយ។",
  ],
  mt_add_done: ["{0} added to {1}.", "បានបន្ថែម {0} ទៅ {1}។"],
  mt_serial: ["Serial", "លេខសៀរៀល"],
  mt_serial_help: [
    "The number printed on the meter. If it has none, use a code such as {0}.",
    "លេខដែលបោះពុម្ពលើនាឡិកាស្ទង់។ បើគ្មាន សូមប្រើកូដដូចជា {0}។",
  ],
  mt_new_serial: ["New meter serial", "លេខសៀរៀលនាឡិកាស្ទង់ថ្មី"],
  mt_new_start: ["First reading", "អំណានដំបូង"],
  mt_start_help: [
    "The number on the new meter now. Often 0.",
    "លេខលើនាឡិកាស្ទង់ថ្មីឥឡូវនេះ។ ជាធម្មតា 0។",
  ],
  mt_why: ["Reason", "មូលហេតុ"],
  mt_why_help: ["Saved in History.", "រក្សាទុកក្នុងប្រវត្តិ។"],
  mt_e_serial: ["Write the serial.", "សូមសរសេរលេខសៀរៀល។"],
  mt_e_used: [
    "{0} is already used by another meter.",
    "{0} ប្រើដោយនាឡិកាស្ទង់ផ្សេងរួចហើយ។",
  ],
  mt_e_date: ["Write the date.", "សូមសរសេរថ្ងៃ។"],
  mt_e_future: ["The date cannot be after today.", "ថ្ងៃមិនអាចក្រោយថ្ងៃនេះ។"],
  mt_e_before: ["The date cannot be before {0}.", "ថ្ងៃមិនអាចមុន {0}។"],
  // new (server rule: the new meter starts at least one day after the old one was found broken)
  mt_e_after: [
    "The new meter must be put in at least one day after the old one was found broken.",
    "នាឡិកាស្ទង់ថ្មីត្រូវដាក់យ៉ាងហោចណាស់មួយថ្ងៃក្រោយរកឃើញនាឡិកាស្ទង់ចាស់ខូច។",
  ],
  mt_e_why: ["Write what is wrong.", "សូមសរសេរបញ្ហា។"],
  mt_replace_t: ["Replace {0}?", "ប្តូរ {0}?"],
  mt_found: ["Found broken on", "រកឃើញខូចថ្ងៃ"],
  // new
  mt_found_help: [
    "Not before the last good reading ({0}).",
    "មិនមុនអំណានល្អចុងក្រោយ ({0})។",
  ],
  mt_new_day: ["Put in on", "ដាក់ថ្ងៃ"],
  // changed: V1 has no estimate screen yet.
  mt_replace_c: [
    "{0} stops on the day the new meter is put in. It stays in the history with all its readings. Use from the day after the last good reading until the new meter starts is estimated from earlier months. This is saved in History.",
    "{0} ឈប់នៅថ្ងៃដាក់នាឡិកាស្ទង់ថ្មី។ វានៅក្នុងប្រវត្តិ ជាមួយអំណានទាំងអស់។ ការប្រើតាំងពីថ្ងៃបន្ទាប់ពីអំណានល្អចុងក្រោយ រហូតនាឡិកាស្ទង់ថ្មីចាប់ផ្តើម ត្រូវប៉ាន់ស្មានពីខែមុនៗ។ ការនេះរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  mt_replace_done: ["{0} replaced by {1}.", "បានប្តូរ {0} ដោយ {1}។"],
  // new
  mt_no_reading: [
    "This meter has no reading yet, so it cannot be replaced here.",
    "នាឡិកាស្ទង់នេះមិនទាន់មានអំណាន ដូច្នេះមិនអាចប្តូរនៅទីនេះបានទេ។",
  ],
  mt_reads: ["Readings", "អំណាន"],
  mt_facts: ["About this meter", "អំពីនាឡិកាស្ទង់នេះ"],
  // new
  mt_new_meter: ["Replaced by", "ប្តូរដោយ"],
  // new
  mt_old_meter: ["Replaced", "ជំនួស"],
  mt_failed: ["Found broken", "រកឃើញខូច"],
  mt_keep: [
    "Meters are never deleted. A replaced meter stays here with all its readings.",
    "នាឡិកាស្ទង់មិនដែលលុបទេ។ នាឡិកាស្ទង់ដែលបានប្តូរនៅទីនេះ ជាមួយអំណានទាំងអស់។",
  ],
  // new
  back: ["Back to Meters", "ត្រឡប់ទៅនាឡិកាស្ទង់"],
  // new
  mt_not_found: ["This meter was not found.", "រកមិនឃើញនាឡិកាស្ទង់នេះទេ។"],
  close: ["Cancel", "បោះបង់"],
  // new
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  // new
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  // new
  unknown: [
    "No answer came back, so it may or may not be saved. Try again: the same request is saved only once.",
    "គ្មានចម្លើយត្រឡប់មកវិញ ដូច្នេះប្រហែលបាន ឬមិនបានរក្សាទុក។ សូមព្យាយាមម្តងទៀត៖ សំណើដដែលរក្សាទុកតែម្តង។",
  ],
  // new
  m_refused: [
    "It was not saved. Check the values and try again.",
    "មិនបានរក្សាទុកទេ។ សូមពិនិត្យតម្លៃ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  m_conflict: [
    "The meters changed while the form was open, so the list was read again. Check and try again.",
    "នាឡិកាស្ទង់បានផ្លាស់ប្តូរ ពេលទម្រង់កំពុងបើក ដូច្នេះបញ្ជីត្រូវបានអានម្តងទៀត។ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  // R4c Import (mock-up i18n.js and i18n9.js; owner 22/10/2026: one row per Unit)
  im_btn: ["Import", "នាំចូល"],
  im_t: ["Import readings from a spreadsheet", "នាំចូលអំណានពីតារាង"],
  im_intro: [
    "Import the readings for reading day {0} from an .xlsx or .csv file.",
    "នាំចូលអំណានសម្រាប់ថ្ងៃអាន {0} ពីឯកសារ .xlsx ឬ .csv។",
  ],
  im_cols: [
    "One row for each Unit, with three columns: Unit, Electricity, Water. The Units are already filled in, so staff type only the readings. No meter numbers.",
    "មួយជួរសម្រាប់បន្ទប់នីមួយៗ មានបីជួរឈរ៖ បន្ទប់ អគ្គិសនី ទឹក។ បន្ទប់បានបំពេញរួចហើយ ដូច្នេះបុគ្គលិកវាយតែអំណានប៉ុណ្ណោះ។ គ្មានលេខនាឡិកាស្ទង់ទេ។",
  ],
  im_blank: ["Download the blank file", "ទាញយកឯកសារទទេ"],
  im_blank_s: [
    "Every Unit is filled in. Print it or fill it in on the tablet.",
    "បន្ទប់ទាំងអស់បានបំពេញរួច។ បោះពុម្ព ឬបំពេញលើថេប្លេត។",
  ],
  // new
  im_blank_failed: [
    "The blank file could not be made just now. Try again.",
    "មិនអាចបង្កើតឯកសារទទេបានទេឥឡូវនេះ។ សូមព្យាយាមម្តងទៀត។",
  ],
  im_file: ["Spreadsheet file", "ឯកសារតារាង"],
  // changed: the mock-up's sample file is not in the app
  im_e_none: ["Choose a file first.", "សូមជ្រើសឯកសារជាមុនសិន។"],
  im_check: ["Check the file", "ពិនិត្យឯកសារ"],
  // new
  checking: ["Checking…", "កំពុងពិនិត្យ…"],
  // new
  im_e_type: ["Choose an .xlsx or .csv file.", "សូមជ្រើសឯកសារ .xlsx ឬ .csv។"],
  // new
  im_e_read: [
    "This file could not be read. Save it again as .xlsx or .csv and try again.",
    "មិនអាចអានឯកសារនេះបានទេ។ សូមរក្សាទុកម្តងទៀតជា .xlsx ឬ .csv ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  im_e_big: [
    "The file is bigger than 2 MB. It needs only one row for each Unit.",
    "ឯកសារធំជាង 2 MB។ វាត្រូវការតែមួយជួរសម្រាប់បន្ទប់នីមួយៗ។",
  ],
  // new
  im_e_columns: [
    "The first row needs the three column names Unit, Electricity and Water.",
    "ជួរទីមួយត្រូវមានឈ្មោះជួរឈរបី៖ Unit, Electricity និង Water។",
  ],
  // new
  im_e_rows: [
    "The file has too many rows. It needs one row for each Unit.",
    "ឯកសារមានជួរច្រើនពេក។ វាត្រូវការមួយជួរសម្រាប់បន្ទប់នីមួយៗ។",
  ],
  // new
  im_e_empty_file: ["The file has no readings.", "ឯកសារគ្មានអំណានទេ។"],
  // new
  im_e_failed: [
    "The file could not be checked. Check the connection and try again.",
    "មិនអាចពិនិត្យឯកសារបានទេ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  im_e_allowed: ["You may not import readings.", "អ្នកមិនអាចនាំចូលអំណានបានទេ។"],
  im_t2: ["Check readings", "ពិនិត្យអំណាន"],
  im_prev: ["Previous Reading", "អំណានមុន"],
  im_cur: ["Current Reading", "អំណានបច្ចុប្បន្ន"],
  im_result: ["Check", "ការពិនិត្យ"],
  im_ready: ["Ready", "រួចរាល់"],
  im_sum: [
    "{0} readings. {1} are ready. {2} need fixing.",
    "អំណាន {0}។ {1} រួចរាល់។ {2} ត្រូវកែ។",
  ],
  im_e_empty: ["Empty. Type the reading.", "ទទេ។ សូមវាយអំណាន។"],
  im_e_lower: ["Lower than previous", "ទាបជាងអំណានមុន"],
  im_e_broken: [
    "Meter broken. Replace it first.",
    "នាឡិកាស្ទង់ខូច។ សូមប្តូរជាមុនសិន។",
  ],
  im_e_unit: ["There is no Unit {0}.", "គ្មានបន្ទប់ {0} ទេ។"],
  // new
  im_e_no_unit: ["Row {0} has no Unit.", "ជួរទី {0} គ្មានបន្ទប់។"],
  // new
  im_e_twice: [
    "{0} is on more than one row (rows {1}). Keep one row.",
    "{0} មាននៅលើជួរច្រើនជាងមួយ (ជួរទី {1})។ សូមទុកតែមួយជួរ។",
  ],
  // new
  im_e_no_meter: [
    "This Unit has no {0} meter. A Manager adds it on the Meters tab.",
    "បន្ទប់នេះគ្មាននាឡិកាស្ទង់{0}ទេ។ អ្នកគ្រប់គ្រងបន្ថែមវានៅផ្ទាំងនាឡិកាស្ទង់។",
  ],
  // new
  im_e_number: ["Not a whole number", "មិនមែនលេខគត់"],
  // new
  im_e_saved: ["Already saved this month: {0}", "បានរក្សាទុករួចខែនេះ៖ {0}"],
  // new
  im_w_high: [
    "Much more than usual (about {0}). Check the meter.",
    "ច្រើនជាងធម្មតា (ប្រហែល {0})។ សូមពិនិត្យនាឡិកាស្ទង់។",
  ],
  im_how: ["What to confirm", "អ្វីត្រូវបញ្ជាក់"],
  im_good: [
    "Confirm the {0} ready readings now. Fix the other {1} on the screen.",
    "បញ្ជាក់អំណាន {0} ដែលរួចរាល់ឥឡូវ។ កែ {1} ផ្សេងទៀតលើអេក្រង់។",
  ],
  im_all: [
    "Confirm nothing until every reading is right.",
    "មិនបញ្ជាក់អ្វីទេ រហូតដល់អំណានទាំងអស់ត្រឹមត្រូវ។",
  ],
  im_note: [
    "Each reading is checked again when it is saved, the same as typing it in. This is saved in History.",
    "អំណាននីមួយៗត្រូវពិនិត្យម្តងទៀតពេលរក្សាទុក ដូចការវាយបញ្ចូល។ ការនេះរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  // changed: the mock-up sentence about acting as the Manager is left out
  im_who: [
    "A Manager or a user allowed to confirm readings checks this list and confirms it.",
    "អ្នកគ្រប់គ្រង ឬអ្នកប្រើដែលមានសិទ្ធិបញ្ជាក់អំណាន ពិនិត្យបញ្ជីនេះ ហើយបញ្ជាក់។",
  ],
  im_photo: [
    "No meter photos are needed. Report a meter problem on a Unit Check.",
    "មិនត្រូវការរូបថតនាឡិកាស្ទង់ទេ។ រាយការណ៍បញ្ហានាឡិកាស្ទង់លើការពិនិត្យបន្ទប់។",
  ],
  im_save: ["Confirm readings", "បញ្ជាក់អំណាន"],
  // new
  im_e_atomic_big: [
    "There are more than 100 readings, too many to confirm in one step. Choose the first choice.",
    "មានអំណានច្រើនជាង 100 ច្រើនពេកសម្រាប់បញ្ជាក់ក្នុងមួយជំហាន។ សូមជ្រើសជម្រើសទីមួយ។",
  ],
  // new
  im_e_changed: [
    "Nothing was confirmed. The meters changed while the list was open, so the readings were read again. Import the file again.",
    "មិនបានបញ្ជាក់អ្វីទេ។ នាឡិកាស្ទង់បានផ្លាស់ប្តូរ ពេលបញ្ជីកំពុងបើក ដូច្នេះអំណានត្រូវបានអានម្តងទៀត។ សូមនាំចូលឯកសារម្តងទៀត។",
  ],
  im_done: ["{0} readings confirmed from {1}.", "បានបញ្ជាក់អំណាន {0} ពី {1}។"],
  im_none: [
    "Nothing confirmed from {0}. Fix the file and import it again.",
    "មិនបានបញ្ជាក់អ្វីពី {0}។ សូមកែឯកសារ ហើយនាំចូលម្តងទៀត។",
  ],
  // new: why the server refused one reading
  im_r_conflict: [
    "The meter changed. Check it on the screen.",
    "នាឡិកាស្ទង់បានផ្លាស់ប្តូរ។ សូមពិនិត្យលើអេក្រង់។",
  ],
  // new
  im_r_refused: [
    "Refused. It may be lower than a reading already saved.",
    "ត្រូវបានបដិសេធ។ វាអាចទាបជាងអំណានដែលបានរក្សាទុករួច។",
  ],
  // new
  im_r_failed: [
    "Not saved. Type it on the screen.",
    "មិនបានរក្សាទុក។ សូមវាយវាលើអេក្រង់។",
  ],
  required: ["Required", "ត្រូវការ"],
  optional: ["Optional", "ស្រេចចិត្ត"],
} as const satisfies Record<string, readonly [string, string]>;

export type UtilitiesTextKey = keyof typeof TEXT;

export function utt(
  language: Language,
  key: UtilitiesTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "en" ? 0 : 1];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

const MONTHS = {
  en: [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ],
  km: [
    "មករា",
    "កុម្ភៈ",
    "មីនា",
    "មេសា",
    "ឧសភា",
    "មិថុនា",
    "កក្កដា",
    "សីហា",
    "កញ្ញា",
    "តុលា",
    "វិច្ឆិកា",
    "ធ្នូ",
  ],
};

/** "2026-11" or "2026-11-24" → "November 2026". */
export function monthText(language: Language, day: string): string {
  const month = MONTHS[language][Number(day.slice(5, 7)) - 1] ?? "";
  return `${month} ${day.slice(0, 4)}`;
}
