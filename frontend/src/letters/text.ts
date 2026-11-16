// V1-058 R3: the words of the Letters screen in English and Khmer, from the owner's mock-up
// (i18n10.js, app10.js). Khmer needs the native check before the app is used. Lines marked
// "new" are not in the mock-up.

import type { Language } from "../signInText";
import { singular } from "../shell/plural";

const TEXT = {
  // DL-237 (owner 13 Nov 2026): notices on day 10, 20 and 25, the termination letter on
  // day 30. The Khmer of the changed lines is new and needs the native check.
  sub: [
    "Rent notices on day 10, 20 and 25, the termination letter on day 30, and Lease rule warnings",
    "លិខិតជូនដំណឹងថ្លៃឈ្នួលថ្ងៃទី១០ ទី២០ និងទី២៥ លិខិតបញ្ចប់កិច្ចសន្យាថ្ងៃទី៣០ និងការព្រមានអំពីវិន័យកិច្ចសន្យា",
  ],
  // new
  as_of: ["as of {0}", "គិតត្រឹម {0}"],
  // UI v81 round 2: the design's names (sub-tabs and the C26 card). Khmer needs the native check.
  tab_rent: ["Rent arrears notices", "សេចក្ដីជូនដំណឹងបំណុលថ្លៃឈ្នួល"],
  tab_warn: ["Lease breach notices", "សេចក្ដីជូនដំណឹងរំលោភកិច្ចសន្យា"],
  // new
  loading: ["Loading the letters…", "កំពុងផ្ទុកលិខិត…"],
  // new
  failed: [
    "The letters could not be loaded. Check the connection and try again.",
    "មិនអាចអានលិខិតបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  // new
  no_property: [
    "Choose the Property in Settings first.",
    "សូមជ្រើសរើសអគារក្នុងការកំណត់ជាមុនសិន។",
  ],
  // new
  not_allowed: [
    "You are not allowed to see this list.",
    "អ្នកមិនត្រូវបានអនុញ្ញាតឱ្យមើលបញ្ជីនេះទេ។",
  ],
  // UI v81: the card keeps the menu's word, "Notices" (the Home card is "Notices due" too).
  c_due: ["Notices due", "លិខិតត្រូវផ្តល់"],
  c_due_s: [
    "A notice on paper, or the termination letter",
    "លិខិតជូនដំណឹងជាក្រដាស ឬលិខិតបញ្ចប់កិច្ចសន្យា",
  ],
  c_w20: ["Notices given", "បានផ្តល់លិខិតជូនដំណឹង"],
  c_w20_s: ["Waiting for the next day", "រង់ចាំថ្ងៃបន្ទាប់"],
  c_w30: ["Termination letter sent", "បានផ្ញើលិខិតបញ្ចប់កិច្ចសន្យា"],
  c_w30_s: ["The Lease may be ended", "អាចបញ្ចប់កិច្ចសន្យាបាន"],
  // new
  showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  // new
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  late_open: [
    "Day 30 has passed and the three notices are not all given. The termination letter waits for them.",
    "ថ្ងៃទី៣០ បានកន្លង ហើយលិខិតជូនដំណឹងទាំងបីមិនទាន់ផ្តល់គ្រប់ទេ។ លិខិតបញ្ចប់កិច្ចសន្យារង់ចាំលិខិតទាំងនោះ។",
  ],
  cases: ["Unpaid Rent after day 10", "ថ្លៃឈ្នួលមិនទាន់បង់ក្រោយថ្ងៃទី១០"],
  col_case: ["Unit and Customer", "បន្ទប់ និងអតិថិជន"],
  col_month: ["Rent month", "ខែថ្លៃឈ្នួល"],
  col_20: ["Day-20 letter", "លិខិតថ្ងៃទី២០"],
  col_30: ["Day-30 letter", "លិខិតថ្ងៃទី៣០"],
  col_next: ["Next step", "ជំហានបន្ទាប់"],
  // new: the mock-up's two letter columns share one, so the table fits an iPad
  col_letters: ["Notices", "លិខិត"],
  dayn: ["Day {0}", "ថ្ងៃទី {0}"],
  due_date: ["Due Date {0}", "ថ្ងៃផុតកំណត់ {0}"],
  // new: the mock-up's "Rent still owed" column, as a line under the Customer
  owed_line: ["{0} Rent owed", "ថ្លៃឈ្នួលជំពាក់ {0}"],
  given: ["Given {0}", "បានផ្តល់ {0}"],
  due_since: ["Due since {0}", "ត្រូវផ្តល់តាំងពី {0}"],
  on: ["On {0}", "នៅ {0}"],
  rec: ["Record letter", "កត់ត្រាលិខិត"],
  // new (DL-237)
  rec_hand: ["Record by hand", "កត់ត្រាដោយដៃ"],
  // new (DL-237)
  bot_sends: [
    "The Tenant bot sends notice {0} at 09:00.",
    "Tenant bot ផ្ញើលិខិតជូនដំណឹងទី {0} នៅម៉ោង 09:00។",
  ],
  wait_step: ["Wait for day {0} ({1})", "រង់ចាំថ្ងៃទី {0} ({1})"],
  // new (DL-237)
  term_letter: ["Termination letter", "លិខិតបញ្ចប់កិច្ចសន្យា"],
  // new (DL-237)
  term_wait: [
    "Termination letter ready: a Manager or the Owner sends it",
    "លិខិតបញ្ចប់កិច្ចសន្យារួចរាល់៖ អ្នកគ្រប់គ្រង ឬម្ចាស់ជាអ្នកផ្ញើ",
  ],
  term: ["End the Lease", "បញ្ចប់កិច្ចសន្យា"],
  // UI v81 (owner): the role is text beside the button, "Manager only".
  mgr_badge: ["Manager only", "សម្រាប់អ្នកគ្រប់គ្រងប៉ុណ្ណោះ"],
  // new
  no_step: ["Nothing to do now", "គ្មានអ្វីត្រូវធ្វើឥឡូវ"],
  none: [
    "No Rent is unpaid on day 10. No letters are due.",
    "គ្មានថ្លៃឈ្នួលមិនទាន់បង់នៅថ្ងៃទី១០ទេ។ គ្មានលិខិតត្រូវផ្តល់ទេ។",
  ],
  // new
  none_here: ["No letters here.", "គ្មានលិខិតនៅទីនេះទេ។"],
  how_count: [
    "Day 1 is the 1st of the Rent month. November Rent gives the notices on 10/11, 20/11 and 25/11 and the termination letter on 30/11. No notice comes before the Invoice Due Date has passed. Only unpaid Rent counts, not Services or Utilities. A tenant with Telegram gets the three notices from the Tenant bot at 09:00. For a tenant without Telegram, print the letter and record it here.",
    "ថ្ងៃទី១ គឺថ្ងៃទី១ នៃខែថ្លៃឈ្នួល។ ថ្លៃឈ្នួលខែវិច្ឆិកា ផ្តល់លិខិតជូនដំណឹងនៅ 10/11, 20/11 និង 25/11 ហើយលិខិតបញ្ចប់កិច្ចសន្យានៅ 30/11។ គ្មានលិខិតជូនដំណឹងមុនថ្ងៃផុតកំណត់វិក្កយបត្រកន្លងទេ។ គិតតែថ្លៃឈ្នួលមិនទាន់បង់ មិនគិតសេវា ឬទឹកភ្លើងទេ។ អ្នកជួលដែលមាន Telegram ទទួលលិខិតជូនដំណឹងទាំងបីពី Tenant bot នៅម៉ោង 09:00។ សម្រាប់អ្នកជួលគ្មាន Telegram សូមបោះពុម្ពលិខិត ហើយកត់ត្រានៅទីនេះ។",
  ],
  nothing: [
    "A letter never ends the Lease, adds a fee or changes the Parking by itself. The Owner or a Manager decides each next step.",
    "លិខិតមិនបញ្ចប់កិច្ចសន្យា បន្ថែមថ្លៃ ឬប្តូរចំណតដោយខ្លួនឯងទេ។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងសម្រេចជំហានបន្ទាប់នីមួយៗ។",
  ],
  // new
  letters_failed: [
    "The letters of {0} could not be loaded. Retry before recording one.",
    "មិនអាចអានលិខិតរបស់ {0} បានទេ។ សូមព្យាយាមម្តងទៀត មុនកត់ត្រា។",
  ],
  d_t: ["Record a Rent letter · {0}", "កត់ត្រាលិខិតថ្លៃឈ្នួល · {0}"],
  customer: ["Customer", "អតិថិជន"],
  d_owed: ["Rent still owed today", "ថ្លៃឈ្នួលនៅជំពាក់ថ្ងៃនេះ"],
  d_owed_note: [
    "Only the Rent line counts. Day 1 is {0}.",
    "គិតតែជួរថ្លៃឈ្នួល។ ថ្ងៃទី១ គឺ {0}។",
  ],
  d_which: ["Which letter", "លិខិតមួយណា"],
  d_10: ["Notice 1 (day 10)", "លិខិតជូនដំណឹងទី១ (ថ្ងៃទី១០)"],
  d_20: ["Notice 2 (day 20)", "លិខិតជូនដំណឹងទី២ (ថ្ងៃទី២០)"],
  d_25: ["Notice 3 (day 25)", "លិខិតជូនដំណឹងទី៣ (ថ្ងៃទី២៥)"],
  d_given: ["already recorded", "បានកត់ត្រារួច"],
  d_date: ["Date given", "ថ្ងៃផ្តល់"],
  // new
  d_date_today: [
    "Today, {0}. The app records the day the letter is recorded, so record it on the day it is given.",
    "ថ្ងៃនេះ {0}។ កម្មវិធីកត់ត្រាថ្ងៃដែលកត់ត្រាលិខិត ដូច្នេះសូមកត់ត្រានៅថ្ងៃដែលផ្តល់។",
  ],
  d_how: ["How it was given", "របៀបផ្តល់"],
  d_how_e: ["Choose how it was given.", "សូមជ្រើសរបៀបផ្តល់។"],
  h_HAND: ["Handed to the tenant", "ប្រគល់ដល់អ្នកជួល"],
  h_DOOR: ["Left at the Parking with a witness", "ទុកនៅចំណត ដោយមានសាក្សី"],
  // new (owner 2026-10-25)
  h_EMAIL: ["Sent by email", "ផ្ញើតាមអ៊ីមែល"],
  h_TG: ["Sent by Telegram", "ផ្ញើតាម Telegram"],
  // new (owner 2026-10-25)
  h_WA: ["Sent by WhatsApp", "ផ្ញើតាម WhatsApp"],
  h_OTHER: ["Other", "ផ្សេងទៀត"],
  d_detail: ["Details", "ព័ត៌មានលម្អិត"],
  d_detail_h: [
    "For example: the tenant signed our copy; or the witness's name.",
    "ឧទាហរណ៍៖ អ្នកជួលបានចុះហត្ថលេខាលើច្បាប់ចម្លងយើង ឬឈ្មោះសាក្សី។",
  ],
  d_detail_e: ["Write the details.", "សូមសរសេរព័ត៌មានលម្អិត។"],
  d_no: ["Notice number", "លេខលិខិត"],
  d_no_ph: [
    "The number written on the paper letter",
    "លេខដែលសរសេរលើលិខិតក្រដាស",
  ],
  // new
  d_no_e: [
    "Write the letter number. Each notice needs one.",
    "សូមសរសេរលេខលិខិត។ លិខិតជូនដំណឹងនីមួយៗត្រូវការលេខ។",
  ],
  // new
  d_which_e: ["Choose the letter.", "សូមជ្រើសលិខិត។"],
  required: ["Required", "ត្រូវការ"],
  optional: ["Optional", "ស្រេចចិត្ត"],
  close: ["Cancel", "បោះបង់"],
  // new
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  // new
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  d_save: ["Record letter", "កត់ត្រាលិខិត"],
  d_toast: ["{0} recorded for {1}.", "បានកត់ត្រា {0} សម្រាប់ {1}។"],
  // new (DL-237): the termination letter of day 30, sent by a Manager or the Owner.
  tl_t: ["Termination letter · {0}", "លិខិតបញ្ចប់កិច្ចសន្យា · {0}"],
  tl_note: [
    "Day 30 has come and the three notices were given. This records the termination letter with its end date. It does not end the Lease: Terminate does, on the Lease page, once the end date has come.",
    "ថ្ងៃទី៣០ បានមកដល់ ហើយលិខិតជូនដំណឹងទាំងបីបានផ្តល់រួច។ នេះកត់ត្រាលិខិតបញ្ចប់កិច្ចសន្យា ជាមួយថ្ងៃបញ្ចប់។ វាមិនបញ្ចប់កិច្ចសន្យាទេ៖ ប៊ូតុងបញ្ចប់នៅទំព័រកិច្ចសន្យាធ្វើវា ពេលថ្ងៃបញ្ចប់មកដល់។",
  ],
  tl_ends: ["The Lease ends on", "កិច្ចសន្យាបញ្ចប់នៅ"],
  tl_ends_h: [
    "The standard Lease gives 30 days' landlord notice.",
    "កិច្ចសន្យាស្តង់ដារ ផ្តល់ការជូនដំណឹងពីម្ចាស់ 30 ថ្ងៃ។",
  ],
  tl_ends_e: [
    "The end date cannot be before today.",
    "ថ្ងៃបញ្ចប់មិនអាចមុនថ្ងៃនេះទេ។",
  ],
  tl_no_e: ["Write the letter number.", "សូមសរសេរលេខលិខិត។"],
  tl_tg: [
    "Print the letter and give it on paper. The paper letter is the official copy. The Tenant bot also sends a copy in Telegram when you press Send.",
    "សូមបោះពុម្ពលិខិត ហើយផ្តល់ជាក្រដាស។ លិខិតក្រដាសគឺជាច្បាប់ផ្លូវការ។ Tenant bot ក៏ផ្ញើច្បាប់ចម្លងតាម Telegram ពេលអ្នកចុចផ្ញើ។",
  ],
  tl_paper: [
    "This tenant has no Telegram link. Print the letter and give it on paper.",
    "អ្នកជួលនេះគ្មានតំណ Telegram ទេ។ សូមបោះពុម្ពលិខិត ហើយផ្តល់ជាក្រដាស។",
  ],
  tl_send: ["Send termination letter", "ផ្ញើលិខិតបញ្ចប់កិច្ចសន្យា"],
  tl_toast: [
    "Termination letter recorded for {0}.",
    "បានកត់ត្រាលិខិតបញ្ចប់កិច្ចសន្យាសម្រាប់ {0}។",
  ],
  // Stored with the record, in English.
  tl_text: [
    "The Lease of {0} ends on {1} because the Rent is still unpaid after the notices of day 10, day 20 and day 25.",
    "កិច្ចសន្យា {0} បញ្ចប់នៅ {1} ព្រោះថ្លៃឈ្នួលនៅមិនទាន់បង់ បន្ទាប់ពីលិខិតជូនដំណឹងថ្ងៃទី១០ ទី២០ និងទី២៥។",
  ],
  // new
  unknown: [
    "No answer came back, so it is not known whether it was saved. Press Try again: the same request is sent and it is saved only once.",
    "មិនមានចម្លើយត្រឡប់មកវិញ ដូច្នេះមិនដឹងថាបានរក្សាទុកឬអត់។ សូមចុច ព្យាយាមម្តងទៀត៖ សំណើដដែលត្រូវបានផ្ញើ ហើយរក្សាទុកតែម្តង។",
  ],
  // new
  refused: [
    "It was not saved. Check the values; if they look right, a rule or your access stopped it.",
    "មិនបានរក្សាទុកទេ។ សូមពិនិត្យតម្លៃ។ បើត្រឹមត្រូវ ច្បាប់ ឬសិទ្ធិរបស់អ្នកបានបញ្ឈប់វា។",
  ],
  // new
  conflict: [
    "Somebody changed this meanwhile. The list was read again; check it and try once more.",
    "មាននរណាម្នាក់បានប្តូរវាក្នុងពេលនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត។ សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  lw_rule: [
    "Three written warnings about the same or a repeated breach come before ending a Lease for a rule breach. Three warnings count even when they are about different breaches. A serious breach (a crime, or danger to people or the building) may end it at once.",
    "ការព្រមានជាលាយលក្ខណ៍អក្សរបីដង អំពីការរំលោភដដែល ឬម្តងហើយម្តងទៀត ត្រូវមានមុនបញ្ចប់កិច្ចសន្យាដោយសារការរំលោភវិន័យ។ ការព្រមានបីដងរាប់ ទោះបីអំពីការរំលោភខុសគ្នាក៏ដោយ។ ការរំលោភធ្ងន់ធ្ងរ (បទល្មើស ឬគ្រោះថ្នាក់ដល់មនុស្ស ឬអគារ) អាចបញ្ចប់វាភ្លាម។",
  ],
  lw_lease: ["Lease", "កិច្ចសន្យា"],
  lw_col_n: ["Warnings", "ការព្រមាន"],
  lw_col_last: ["Last warning", "ការព្រមានចុងក្រោយ"],
  lw_col_what: ["Breach", "ការរំលោភ"],
  lw_n: ["{0} of 3", "{0} ក្នុង ៣"],
  lw_new: ["Record warning", "កត់ត្រាការព្រមាន"],
  lw_none: [
    "No Lease breach notices recorded.",
    "គ្មានការព្រមានវិន័យកិច្ចសន្យាដែលបានកត់ត្រាទេ។",
  ],
  // new
  lw_some_failed: [
    "The warnings of {0} could not be loaded. Retry to see them.",
    "មិនអាចអានការព្រមានរបស់ {0} បានទេ។ សូមព្យាយាមម្តងទៀត។",
  ],
  lw_d_t: ["Record a Lease rule warning", "កត់ត្រាការព្រមានវិន័យកិច្ចសន្យា"],
  lw_d_vdate: ["Date of the breach", "ថ្ងៃនៃការរំលោភ"],
  lw_d_wdate: ["Date the warning was given", "ថ្ងៃផ្តល់ការព្រមាន"],
  // new
  lw_d_date_e: [
    "The breach comes first, then the warning; neither after today.",
    "ការរំលោភមកមុន បន្ទាប់មកការព្រមាន។ មិនក្រោយថ្ងៃនេះទេ។",
  ],
  lw_d_what: ["What happened", "អ្វីបានកើតឡើង"],
  lw_d_what_e: ["Write what happened.", "សូមសរសេរអ្វីដែលបានកើតឡើង។"],
  lw_d_clause: ["Lease article", "មាត្រាកិច្ចសន្យា"],
  lw_d_clause_e: [
    "Write the Lease article, for example 11.3.",
    "សូមសរសេរមាត្រាកិច្ចសន្យា ឧទាហរណ៍ 11.3។",
  ],
  lw_d_note: [
    "A warning adds no fee and does not end the Lease. Warning {0} of 3 for this Lease.",
    "ការព្រមានមិនបន្ថែមថ្លៃ ហើយមិនបញ្ចប់កិច្ចសន្យាទេ។ ការព្រមានទី {0} ក្នុង ៣ សម្រាប់កិច្ចសន្យានេះ។",
  ],
  // new
  lw_d_no_lease: [
    "No Lease has a recorded move-in, so there is nobody to warn.",
    "គ្មានកិច្ចសន្យាណាមានការចូលនៅដែលបានកត់ត្រាទេ ដូច្នេះគ្មាននរណាត្រូវព្រមាន។",
  ],
  // new
  lw_d_ctx_failed: [
    "The next warning number could not be loaded. Close and try again.",
    "មិនអាចអានលេខការព្រមានបន្ទាប់បានទេ។ សូមបិទ ហើយព្យាយាមម្តងទៀត។",
  ],
  lw_toast: [
    "Warning {0} recorded for {1}.",
    "បានកត់ត្រាការព្រមានទី {0} សម្រាប់ {1}។",
  ],
  // new
  lease_name: ["Lease · {0}", "កិច្ចសន្យា · {0}"],
  // new
  records: ["Earlier letter forms", "ទម្រង់លិខិតពីមុន"],
  // new
  records_note: [
    "In English until the next steps replace them",
    "ជាភាសាអង់គ្លេស រហូតដល់ជំហានបន្ទាប់ជំនួសវា",
  ],
  // DL-238 (owner 14 Nov 2026): notices for short-stay guests. Khmer is new: native check.
  tab_ss: ["Short-stay guest notices", "សេចក្ដីជូនដំណឹងភ្ញៀវស្នាក់នៅខ្លី"],
  ss_rule: [
    "The Tenant bot sends guests the check-out reminder at {0} the evening before, the late check-out notice {1} minutes after the time to leave, and a note of a charge still unpaid from {2} the next day. A guest with no Telegram is told in person.",
    "Tenant bot ផ្ញើទៅភ្ញៀវនូវការរំលឹកអំពីការចាកចេញនៅម៉ោង {0} ល្ងាចមុនថ្ងៃចាកចេញ ការជូនដំណឹងចាកចេញយឺត {1} នាទីបន្ទាប់ពីម៉ោងត្រូវចាកចេញ និងការរំលឹកប្រាក់មិនទាន់បង់ចាប់ពីម៉ោង {2} ថ្ងៃបន្ទាប់។ ភ្ញៀវដែលគ្មាន Telegram ត្រូវប្រាប់ផ្ទាល់។",
  ],
  ss_c_tell: ["To tell in person", "ត្រូវប្រាប់ផ្ទាល់"],
  ss_c_stays: ["Guests checked in", "ភ្ញៀវកំពុងស្នាក់នៅ"],
  ss_c_warned: ["Guests with a warning", "ភ្ញៀវដែលមានការព្រមាន"],
  ss_new: ["Give a warning", "ផ្ដល់ការព្រមាន"],
  ss_none: [
    "No notices in the last {0} days.",
    "មិនមានសេចក្ដីជូនដំណឹងក្នុងរយៈពេល {0} ថ្ងៃចុងក្រោយទេ។",
  ],
  ss_col_when: ["Date", "កាលបរិច្ឆេទ"],
  ss_col_guest: ["Unit and guest", "បន្ទប់ និងភ្ញៀវ"],
  ss_col_notice: ["Notice", "សេចក្ដីជូនដំណឹង"],
  ss_col_sent: ["How the guest got it", "របៀបដែលភ្ញៀវបានទទួល"],
  k_CHECK_OUT_REMINDER: ["Check-out reminder", "រំលឹកអំពីការចាកចេញ"],
  k_LATE_CHECK_OUT: ["Late check-out notice", "ជូនដំណឹងចាកចេញយឺត"],
  k_HOUSE_RULE_WARNING: [
    "House-rule warning {0}",
    "ការព្រមានអំពីវិន័យស្នាក់នៅ លើកទី {0}",
  ],
  k_final: ["Final house-rule warning", "ការព្រមានចុងក្រោយអំពីវិន័យស្នាក់នៅ"],
  k_UNPAID_CHARGE: ["Unpaid charge", "ប្រាក់មិនទាន់បង់"],
  ss_d_out: ["Check-out {0}", "ចាកចេញ {0}"],
  ss_d_late: ["Time to leave {0}", "ម៉ោងត្រូវចាកចេញ {0}"],
  ss_d_unpaid: ["{0}: {1} to pay", "{0}៖ ត្រូវបង់ {1}"],
  ss_d_auto: ["Sent by the app", "ផ្ញើដោយកម្មវិធី"],
  ss_d_by: ["By {0}", "ដោយ {0}"],
  t_SENT: ["Sent by Telegram", "បានផ្ញើតាម Telegram"],
  t_WAITING: ["Sending", "កំពុងផ្ញើ"],
  t_NOT_DELIVERED: [
    "Not delivered: tell in person",
    "មិនបានទៅដល់៖ ប្រាប់ផ្ទាល់",
  ],
  t_NO_TELEGRAM: [
    "No Telegram: tell in person",
    "គ្មាន Telegram៖ ប្រាប់ផ្ទាល់",
  ],
  ss_told: ["Told by {0} on {1}", "{0} បានប្រាប់នៅថ្ងៃ {1}"],
  ss_told_btn: ["Told in person", "បានប្រាប់ផ្ទាល់"],
  ss_told_toast: [
    "Marked as told in person: {0}.",
    "បានកត់ថាបានប្រាប់ផ្ទាល់៖ {0}។",
  ],
  ss_d_t: ["Give a house-rule warning", "ផ្ដល់ការព្រមានអំពីវិន័យស្នាក់នៅ"],
  ss_d_guest: ["Guest", "ភ្ញៀវ"],
  ss_d_reason: ["What happened", "អ្វីដែលបានកើតឡើង"],
  ss_d_reason_e: ["Write what happened.", "សូមសរសេរអ្វីដែលបានកើតឡើង។"],
  ss_d_next1: [
    "This is warning 1. A second warning is the final warning.",
    "នេះជាការព្រមានលើកទី ១។ ការព្រមានលើកទី ២ គឺជាការព្រមានចុងក្រោយ។",
  ],
  ss_d_next2: [
    "This is the final warning. After it a Manager may end the stay early; unused nights stay paid.",
    "នេះជាការព្រមានចុងក្រោយ។ បន្ទាប់ពីនេះ អ្នកគ្រប់គ្រងអាចបញ្ចប់ការស្នាក់នៅមុនកាលកំណត់។ យប់ដែលមិនបានប្រើ មិនសងប្រាក់វិញទេ។",
  ],
  ss_d_full: ["final warning given", "បានផ្ដល់ការព្រមានចុងក្រោយ"],
  ss_d_no_stay: [
    "No guest is checked in now.",
    "ឥឡូវនេះមិនមានភ្ញៀវកំពុងស្នាក់នៅទេ។",
  ],
  ss_d_no_tg: [
    "This guest has no Telegram: tell the guest in person.",
    "ភ្ញៀវនេះគ្មាន Telegram៖ សូមប្រាប់ភ្ញៀវផ្ទាល់។",
  ],
  ss_toast_tg: [
    "Warning {0} given to {1} and sent by Telegram.",
    "បានផ្ដល់ការព្រមានលើកទី {0} ដល់ {1} និងបានផ្ញើតាម Telegram។",
  ],
  ss_toast_person: [
    "Warning {0} given to {1}. No Telegram: tell the guest in person.",
    "បានផ្ដល់ការព្រមានលើកទី {0} ដល់ {1}។ គ្មាន Telegram៖ សូមប្រាប់ភ្ញៀវផ្ទាល់។",
  ],
  ss_save_e: [
    "It was not saved. Please try again.",
    "មិនបានរក្សាទុកទេ។ សូមព្យាយាមម្ដងទៀត។",
  ],
} as const;

export type LettersTextKey = keyof typeof TEXT;

/** The text in the chosen language, with {0}, {1} filled in. */
export function ltr(
  language: Language,
  key: LettersTextKey,
  ...values: (string | number)[]
): string {
  return singular(
    TEXT[key][language === "en" ? 0 : 1].replace(/\{(\d)\}/g, (_, n) =>
      String(values[Number(n)] ?? ""),
    ),
  );
}

/** The English words stored with a record, so History reads the same for everyone. */
export function storedText(key: LettersTextKey): string {
  return TEXT[key][0];
}

const MONTHS: Record<Language, string[]> = {
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

/** "2026-11-01" → "November 2026". */
export function monthText(language: Language, day: string): string {
  const month = MONTHS[language][Number(day.slice(5, 7)) - 1] ?? "";
  return `${month} ${day.slice(0, 4)}`;
}
