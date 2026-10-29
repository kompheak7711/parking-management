// V1-058 R3 Move-out: the words of the Move-out list and page in English and Khmer, from the
// owner's mock-up (i18n3.js, app3.js). Khmer needs the native check before the app is used.
// Lines marked "new" are not in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  title: ["Move-out", "ការចាកចេញ"],
  sub: [
    "Leases ending, Parking handed back and Final Settlements",
    "កិច្ចសន្យាជិតបញ្ចប់ ចំណតបានប្រគល់ និងការទូទាត់ចុងក្រោយ",
  ],
  moveout_of: ["Move-out · {0}", "ការចាកចេញ · {0}"],
  c_soon: ["Leaving soon", "ជិតចាកចេញ"],
  c_soon_s: [
    "Lease ends within 60 days, or terminated and still in",
    "កិច្ចសន្យាបញ្ចប់ក្នុង 60 ថ្ងៃ ឬបានបញ្ចប់ហើយនៅមិនទាន់ចេញ",
  ],
  c_out: ["Handed back", "បានប្រគល់ចំណត"],
  c_out_s: [
    "Readings, inspection and charges to finish",
    "អំណាន ការត្រួតពិនិត្យ និងថ្លៃត្រូវបញ្ចប់",
  ],
  c_confirm: ["Waiting for a Manager", "រង់ចាំអ្នកគ្រប់គ្រង"],
  c_confirm_s: [
    "Draft Final Settlement to confirm",
    "សេចក្តីព្រាងការទូទាត់ចុងក្រោយ ត្រូវបញ្ជាក់",
  ],
  c_closed: ["Closed", "បានបិទ"],
  c_closed_s: ["Final Settlement closed", "ការទូទាត់ចុងក្រោយបានបិទ"],
  // new
  settle_failed: [
    "The Final Settlements could not be read, so Waiting for a Manager and Closed are not shown.",
    "មិនអាចអានការទូទាត់ចុងក្រោយបានទេ ដូច្នេះរង់ចាំអ្នកគ្រប់គ្រង និងបានបិទ មិនបង្ហាញទេ។",
  ],
  showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  show_all: ["Show all", "បង្ហាញទាំងអស់"],
  n1: ["1 move-out", "ការចាកចេញ 1"],
  n: ["{0} move-outs", "ការចាកចេញ {0}"],
  none: ["Nothing here.", "គ្មានអ្វីនៅទីនេះទេ។"],
  col_unit: ["Parking", "ចំណត"],
  col_cust: ["Customer", "អតិថិជន"],
  col_end: ["Lease ends", "កិច្ចសន្យាបញ្ចប់"],
  col_hb: ["Handed back", "បានប្រគល់"],
  col_step: ["Step", "ជំហាន"],
  col_dep: ["Deposits held", "ប្រាក់កក់កាន់កាប់"],
  was: ["End Date was {0}", "ថ្ងៃបញ្ចប់គឺ {0}"],
  next_hb: ["Record the hand-back", "កត់ត្រាការប្រគល់ចំណត"],
  next_final: ["Record final readings", "កត់ត្រាអំណានចុងក្រោយ"],
  next_settle: ["Prepare the Final Settlement", "រៀបចំការទូទាត់ចុងក្រោយ"],
  next_confirm: ["A Manager confirms it", "អ្នកគ្រប់គ្រងបញ្ជាក់"],
  // new
  next_none: ["Nothing left to do", "គ្មានអ្វីត្រូវធ្វើទៀតទេ"],
  in_days: ["in {0} days", "ក្នុង {0} ថ្ងៃ"],
  today: ["today", "ថ្ងៃនេះ"],
  ago: ["{0} days ago", "{0} ថ្ងៃមុន"],
  // new
  ago1: ["1 day ago", "1 ថ្ងៃមុន"],
  // new
  in1: ["in 1 day", "ក្នុង 1 ថ្ងៃ"],
  rule_note: [
    "Order of work: hand-back, final readings, inspection and charges, Final Settlement (BR-MOVEOUT-012). One Final Settlement per Lease; corrections after closure are separate records.",
    "លំដាប់ការងារ៖ ប្រគល់ចំណត អំណានចុងក្រោយ ត្រួតពិនិត្យ និងថ្លៃ ការទូទាត់ចុងក្រោយ។ ការទូទាត់ចុងក្រោយតែមួយក្នុងមួយកិច្ចសន្យា; ការកែបន្ទាប់ពីបិទ ជាកំណត់ត្រាដាច់ដោយឡែក។",
  ],
  s_soon: ["Leaving soon", "ជិតចាកចេញ"],
  s_in: ["Still in the Parking", "នៅក្នុងចំណត"],
  s_out: ["Handed back", "បានប្រគល់"],
  // new: terminated before anybody moved in.
  s_skip: ["Never moved in", "មិនដែលចូលស្នាក់នៅ"],
  // new (M5)
  s_settle: ["Final Settlement", "ការទូទាត់ចុងក្រោយ"],
  s_confirm: ["Waiting for a Manager", "រង់ចាំអ្នកគ្រប់គ្រង"],
  s_closed: ["Closed", "បានបិទ"],
  steps_t: ["Move-out steps", "ជំហានចាកចេញ"],
  done: ["Done", "រួចរាល់"],
  todo: ["To do", "ត្រូវធ្វើ"],
  skip: ["Not needed", "មិនចាំបាច់"],
  now: ["Now", "ឥឡូវ"],
  // new (V1-060 B6): step 6 after closure is used only when something comes up later.
  optional: ["If needed", "បើចាំបាច់"],
  st1_t: ["Lease ends", "កិច្ចសន្យាបញ្ចប់"],
  st1_normal: [
    "Lease End Date {0}. Normal end: the Security Deposit pays what is owed, the rest is refunded (DL-032).",
    "ថ្ងៃបញ្ចប់កិច្ចសន្យា {0}។ បញ្ចប់ធម្មតា៖ ប្រាក់កក់សុវត្ថិភាពបង់អ្វីដែលជំពាក់ នៅសល់សងវិញ។",
  ],
  // new: the termination's ground is in its reason.
  st1_term: ["Terminated as of {0}.", "បានបញ្ចប់ត្រឹម {0}។"],
  st1_reason: ["Reason: {0}", "មូលហេតុ៖ {0}"],
  st2_t: ["Hand back the Parking", "ប្រគល់ចំណត"],
  // new: the record keeps the keys in its evidence and the Unit status it set.
  st2_done: [
    "Handed back on {0}. Parking set to {1}.",
    "បានប្រគល់នៅ {0}។ ចំណតត្រូវបានកំណត់ជា {1}។",
  ],
  st2_todo: [
    "The Customer is still in the Parking. Record the real hand-back date when the keys come back.",
    "អតិថិជននៅក្នុងចំណត។ កត់ត្រាថ្ងៃប្រគល់ពិតប្រាកដ ពេលទទួលកូនសោ។",
  ],
  // new
  st2_wait: [
    "The Lease ends on {0}. Record the hand-back on or after that day; to leave earlier, end the Lease with Terminate first.",
    "កិច្ចសន្យាបញ្ចប់នៅ {0}។ កត់ត្រាការប្រគល់នៅ ឬក្រោយថ្ងៃនោះ; ដើម្បីចាកចេញមុន សូមបញ្ចប់កិច្ចសន្យាដោយ បញ្ចប់ ជាមុនសិន។",
  ],
  st2_skip: [
    "Never moved in: nothing to hand back.",
    "មិនដែលចូលស្នាក់នៅ៖ គ្មានអ្វីប្រគល់។",
  ],
  // new: a normal end also records the end of the Lease, which needs leases.terminate.
  st2_manager: [
    "A Manager records this hand-back, because it also ends the Lease at its End Date.",
    "អ្នកគ្រប់គ្រងកត់ត្រាការប្រគល់នេះ ព្រោះវាបញ្ចប់កិច្ចសន្យានៅថ្ងៃបញ្ចប់ផងដែរ។",
  ],
  // new
  st2_no_term: [
    "The termination of this Lease could not be read, so the hand-back cannot be recorded here. Open the Lease and try again later.",
    "មិនអាចអានការបញ្ចប់កិច្ចសន្យានេះបានទេ ដូច្នេះមិនអាចកត់ត្រាការប្រគល់នៅទីនេះបានទេ។ បើកកិច្ចសន្យា ហើយព្យាយាមម្តងទៀតពេលក្រោយ។",
  ],
  // new
  st2_not_allowed: [
    "Your account cannot record a hand-back.",
    "គណនីរបស់អ្នកមិនអាចកត់ត្រាការប្រគល់បានទេ។",
  ],
  // new
  renewed_note: [
    "A signed renewal continues this Lease, so the tenants stay: there is no move-out.",
    "ការបន្តដែលបានចុះហត្ថលេខា បន្តកិច្ចសន្យានេះ ដូច្នេះអ្នកជួលនៅដដែល៖ គ្មានការចាកចេញទេ។",
  ],
  // new
  not_yet_note: [
    "This Lease is not ending within 60 days, so it has no move-out yet.",
    "កិច្ចសន្យានេះមិនបញ្ចប់ក្នុង 60 ថ្ងៃទេ ដូច្នេះមិនទាន់មានការចាកចេញ។",
  ],
  st2_btn: ["Record hand-back", "កត់ត្រាការប្រគល់"],
  st2_date: ["Hand-back date", "ថ្ងៃប្រគល់ចំណត"],
  st2_date_help: [
    "The real date the keys came back. Not later than today.",
    "ថ្ងៃពិតដែលទទួលកូនសោ។ មិនក្រោយថ្ងៃនេះ។",
  ],
  st2_bad: ["Enter a date from {0} to today.", "បញ្ចូលថ្ងៃពី {0} ដល់ថ្ងៃនេះ។"],
  st2_keys: ["All keys returned", "បានប្រគល់កូនសោទាំងអស់"],
  st2_who: ["Who moved out", "អ្នកចាកចេញ"],
  // new
  st2_unit: ["The Parking after the hand-back", "ចំណតបន្ទាប់ពីប្រគល់"],
  st2_note: ["Note (optional)", "កំណត់ចំណាំ (ស្រេចចិត្ត)"],
  st2_c: [
    "The Parking leaves Occupied. Rent for the month of hand-back follows the rule shown.",
    "ចំណតលែងមានអ្នកស្នាក់នៅ។ ថ្លៃឈ្នួលខែប្រគល់ តាមច្បាប់បង្ហាញ។",
  ],
  // new
  st2_ends_too: [
    "This also ends the Lease on its End Date, {0}, as signed. The Security Deposit pays what is owed and the rest is refunded.",
    "នេះក៏បញ្ចប់កិច្ចសន្យានៅថ្ងៃបញ្ចប់ {0} តាមការចុះហត្ថលេខាដែរ។ ប្រាក់កក់សុវត្ថិភាពបង់អ្វីដែលជំពាក់ នៅសល់សងវិញ។",
  ],
  st2_ok: ["Record hand-back", "កត់ត្រាការប្រគល់"],
  st2_toast: [
    "Hand-back recorded. {0} is now {1}.",
    "បានកត់ត្រាការប្រគល់។ {0} ឥឡូវ {1}។",
  ],
  rent_after5: [
    "Handed back on {0}, on or after the 5th: Rent for {1} is due in full.",
    "ប្រគល់នៅ {0} ពីថ្ងៃទី 5 ឡើង៖ ថ្លៃឈ្នួល {1} ត្រូវបង់ពេញ។",
  ],
  // new: the three cases of the owner's rule (03/10/2026) in one line.
  rent_before5: [
    "Handed back on {0}, before the 5th: an unpaid Rent Invoice for {1} is voided by a Manager with a reason; a paid one is kept; a partly paid one keeps the paid part.",
    "ប្រគល់នៅ {0} មុនថ្ងៃទី 5៖ វិក្កយបត្រថ្លៃឈ្នួល {1} មិនទាន់បង់ ត្រូវលុបចោលដោយអ្នកគ្រប់គ្រងដោយមានមូលហេតុ; បានបង់ត្រូវរក្សាទុក; បានបង់ខ្លះរក្សាផ្នែកបានបង់។",
  ],
  cond_CLEANING: ["Cleaning", "កំពុងសម្អាត"],
  cond_UNDER_MAINTENANCE: ["Under maintenance", "កំពុងជួសជុល"],
  cond_OUT_OF_SERVICE: ["Out of service", "ឈប់ប្រើ"],
  st3_t: ["Final meter readings", "អំណាននាឡិកាស្ទង់ចុងក្រោយ"],
  st3_todo: [
    "Read both meters on the hand-back day. The app issues the final Utility Invoice at once (off-cycle).",
    "អាននាឡិកាស្ទង់ទាំងពីរនៅថ្ងៃប្រគល់។ កម្មវិធីចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយភ្លាម។",
  ],
  st3_wait: ["After the hand-back.", "បន្ទាប់ពីប្រគល់ចំណត។"],
  st3_btn: ["Record final readings", "កត់ត្រាអំណានចុងក្រោយ"],
  st3_ok: ["Save and issue the Invoice", "រក្សាទុក និងចេញវិក្កយបត្រ"],
  // new
  st3_ok_only: ["Save the readings", "រក្សាទុកអំណាន"],
  st3_bad: [
    "Each new reading must be a whole number not lower than the last reading.",
    "អំណានថ្មីនីមួយៗត្រូវជាចំនួនគត់ មិនតិចជាងអំណានចុងក្រោយ។",
  ],
  // new
  st3_last: ["Last reading {0} on {1}", "អំណានចុងក្រោយ {0} នៅ {1}"],
  // new
  st3_no_last: [
    "No earlier reading of this meter.",
    "គ្មានអំណានមុននៃនាឡិកាស្ទង់នេះទេ។",
  ],
  // new
  st3_taken: ["{0}, read on {1}", "{0} អាននៅ {1}"],
  // new
  st3_meters_failed: [
    "The meters of this Parking could not be read just now. Close and try again.",
    "មិនអាចអាននាឡិកាស្ទង់នៃចំណតនេះបានទេឥឡូវនេះ។ សូមបិទ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  st3_no_meters: [
    "This Parking has no meter on {0}. Add the meters in Utilities first.",
    "ចំណតនេះគ្មាននាឡិកាស្ទង់នៅ {0} ទេ។ សូមបន្ថែមនាឡិកាស្ទង់ក្នុងទឹកភ្លើងជាមុនសិន។",
  ],
  // new
  st3_none: [
    "This Parking has no meter on {0}, so there are no final readings and no final Utility Invoice.",
    "ចំណតនេះគ្មាននាឡិកាស្ទង់នៅ {0} ទេ ដូច្នេះគ្មានអំណានចុងក្រោយ និងគ្មានវិក្កយបត្រទឹកភ្លើងចុងក្រោយទេ។",
  ],
  st3_note: [
    "Final Utility Invoice at move-out: readings from the last cycle reading to the hand-back date (BR-UTIL-021).",
    "វិក្កយបត្រទឹកភ្លើងចុងក្រោយពេលចាកចេញ៖ អំណានពីអំណានវដ្តចុងក្រោយ ដល់ថ្ងៃប្រគល់ចំណត។",
  ],
  // new
  st3_note_only: [
    "The readings are saved now; a Manager issues the final Utility Invoice from this page.",
    "អំណានត្រូវបានរក្សាទុកឥឡូវនេះ; អ្នកគ្រប់គ្រងចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយពីទំព័រនេះ។",
  ],
  st3_done: [
    "Read on {0}. Final Utility Invoice {1} · {2}.",
    "អាននៅ {0}។ វិក្កយបត្រទឹកភ្លើងចុងក្រោយ {1} · {2}។",
  ],
  // new
  st3_inputs: [
    "Readings saved for {0}. The final Utility Invoice is not issued yet.",
    "បានរក្សាទុកអំណានសម្រាប់ {0}។ វិក្កយបត្រទឹកភ្លើងចុងក្រោយមិនទាន់ចេញទេ។",
  ],
  // new
  st3_issue_btn: [
    "Issue the final Utility Invoice",
    "ចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយ",
  ],
  // new
  st3_no_issue: [
    "A Manager issues the final Utility Invoice.",
    "អ្នកគ្រប់គ្រងចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយ។",
  ],
  // new
  st3_no_invoices: [
    "The Invoices of this Lease could not be read, so this page cannot tell whether the final Utility Invoice is issued. Check Invoices.",
    "មិនអាចអានវិក្កយបត្រនៃកិច្ចសន្យានេះបានទេ ដូច្នេះទំព័រនេះមិនដឹងថាវិក្កយបត្រទឹកភ្លើងចុងក្រោយបានចេញឬនៅ។ សូមពិនិត្យវិក្កយបត្រ។",
  ],
  // new
  st3_not_allowed: [
    "Your account may not record readings for a move-out.",
    "គណនីរបស់អ្នកមិនអាចកត់ត្រាអំណានសម្រាប់ការចាកចេញបានទេ។",
  ],
  st3_toast: [
    "Final Utility Invoice {0} issued.",
    "បានចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយ {0}។",
  ],
  // new
  st3_toast_only: ["Final readings saved.", "បានរក្សាទុកអំណានចុងក្រោយ។"],
  // new
  open_invoice: ["Open Invoice", "បើកវិក្កយបត្រ"],
  // new
  st3_loading: ["Reading the meters…", "កំពុងអាននាឡិកាស្ទង់…"],
  // new
  st3_reading_step: [
    "Reading the final readings and Invoices…",
    "កំពុងអានអំណានចុងក្រោយ និងវិក្កយបត្រ…",
  ],
  // new
  st3_unresolved: [
    "A meter has no final reading yet (recorded in Utilities). Finish it there before the final Utility Invoice.",
    "នាឡិកាស្ទង់មួយមិនទាន់មានអំណានចុងក្រោយទេ (កត់ត្រាក្នុងទឹកភ្លើង)។ សូមបញ្ចប់វានៅទីនោះ មុនវិក្កយបត្រទឹកភ្លើងចុងក្រោយ។",
  ],
  // new
  st3_issue_text: [
    "The final readings of {0} are saved. Issue the final Utility Invoice for the days since the last billed reading.",
    "អំណានចុងក្រោយនៃ {0} ត្រូវបានរក្សាទុក។ ចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយសម្រាប់ថ្ងៃចាប់ពីអំណានដែលបានចេញវិក្កយបត្រចុងក្រោយ។",
  ],
  // new
  st3_unchecked: [
    "{0}, read on {1}, not checked yet",
    "{0} អាននៅ {1} មិនទាន់ពិនិត្យទេ",
  ],
  // new
  st3_unchecked_problem: [
    "A reading of the hand-back day is not checked yet. Check it in Utilities, then try again.",
    "អំណាននៃថ្ងៃប្រគល់មួយមិនទាន់ពិនិត្យទេ។ សូមពិនិត្យវាក្នុងទឹកភ្លើង ហើយព្យាយាមម្តងទៀត។",
  ],
  mh_final: ["Final readings; {0} issued.", "អំណានចុងក្រោយ; បានចេញ {0}។"],
  // new
  mh_readings: ["Final readings saved.", "បានរក្សាទុកអំណានចុងក្រោយ។"],
  k_ELECTRICITY: ["Electricity", "អគ្គិសនី"],
  k_WATER: ["Water", "ទឹក"],
  // new: why a final Utility Invoice was refused
  ur_UTILITY_NOTHING_TO_BILL: [
    "There is nothing to bill: every day up to the hand-back is already on an Invoice.",
    "គ្មានអ្វីត្រូវចេញវិក្កយបត្រទេ៖ ថ្ងៃទាំងអស់ដល់ថ្ងៃប្រគល់មានក្នុងវិក្កយបត្ររួចហើយ។",
  ],
  ur_UTILITY_START_READING_MISSING: [
    "A meter has no starting reading for this Lease. Record it in Utilities, then try again.",
    "នាឡិកាស្ទង់មួយគ្មានអំណានចាប់ផ្តើមសម្រាប់កិច្ចសន្យានេះទេ។ សូមកត់ត្រាវាក្នុងទឹកភ្លើង ហើយព្យាយាមម្តងទៀត។",
  ],
  ur_UTILITY_EARLIER_READING_NOT_FINALIZED: [
    "An earlier month is not billed yet. Bill it in Utilities first, then try again.",
    "ខែមុនមួយមិនទាន់ចេញវិក្កយបត្រទេ។ សូមចេញវាក្នុងទឹកភ្លើងជាមុនសិន ហើយព្យាយាមម្តងទៀត។",
  ],
  ur_UTILITY_UNRESOLVED_FINAL_INPUT: [
    "A meter has no final reading yet.",
    "នាឡិកាស្ទង់មួយមិនទាន់មានអំណានចុងក្រោយទេ។",
  ],
  ur_UTILITY_NOT_MOVED_IN: [
    "The Customer never moved in, so there is no Utility to bill.",
    "អតិថិជនមិនដែលចូលនៅទេ ដូច្នេះគ្មានទឹកភ្លើងត្រូវចេញវិក្កយបត្រ។",
  ],
  ur_UTILITY_LEASE_NOT_TERMINATED: [
    "The Lease is not ended yet.",
    "កិច្ចសន្យាមិនទាន់បញ្ចប់ទេ។",
  ],
  // V1-060 B6 (DL-105): the Invoice uses the rate in effect on the day it is made.
  ur_UTILITY_RATE_NOT_IN_EFFECT: [
    "No electricity or water rate is in effect today, so this Invoice cannot be made yet. In Settings, Rates and services, a rate must start on or before today.",
    "គ្មានអត្រាអគ្គិសនី ឬទឹកដែលមានប្រសិទ្ធភាពនៅថ្ងៃនេះទេ ដូច្នេះមិនទាន់អាចធ្វើវិក្កយបត្រនេះបានទេ។ នៅក្នុង ការកំណត់ អត្រា និងសេវា អត្រាត្រូវចាប់ផ្តើមនៅថ្ងៃនេះ ឬមុនថ្ងៃនេះ។",
  ],
  ur_FORBIDDEN: [
    "Your account may not do this.",
    "គណនីរបស់អ្នកមិនអាចធ្វើការនេះបានទេ។",
  ],
  st4_t: ["Inspection and charges", "ការត្រួតពិនិត្យ និងថ្លៃ"],
  st4_todo: [
    "Inspect the Parking after the hand-back. Each damage charge needs an amount, a reason and evidence; it is recorded once per finding.",
    "ត្រួតពិនិត្យចំណតបន្ទាប់ពីប្រគល់។ ថ្លៃខូចខាតនីមួយៗត្រូវមានចំនួន មូលហេតុ និងភស្តុតាង; កត់ត្រាម្តងក្នុងមួយការរកឃើញ។",
  ],
  st4_insp: ["Inspected on {0}.", "បានត្រួតពិនិត្យនៅ {0}។"],
  st4_findings: ["Damage findings", "ការរកឃើញការខូចខាត"],
  st4_nofind: ["No damage found.", "គ្មានការខូចខាត។"],
  st4_add: ["Add finding", "បន្ថែមការរកឃើញ"],
  st4_pet: ["pet damage", "ខូចខាតដោយសត្វចិញ្ចឹម"],
  st4_ev: ["Evidence", "ភស្តុតាង"],
  st4_clean: ["Cleaning charge", "ថ្លៃសម្អាត"],
  // changed from the mock-up: a charged finding keeps the inspection as it is.
  st4_locked: [
    "A finding is charged, so this inspection is kept as it is. New damage found later is a correction after closure.",
    "ការរកឃើញមួយបានគិតថ្លៃ ដូច្នេះការត្រួតពិនិត្យនេះរក្សាដដែល។ ការខូចខាតរកឃើញក្រោយ ជាការកែបន្ទាប់ពីបិទ។",
  ],
  fd_desc: ["What is damaged", "អ្វីខូចខាត"],
  fd_amt: ["Charge", "ថ្លៃ"],
  fd_ev: ["Evidence (photo names, report)", "ភស្តុតាង (ឈ្មោះរូបថត របាយការណ៍)"],
  fd_pet: [
    "Caused by the pet (Pet Deposit pays this first)",
    "បង្កដោយសត្វចិញ្ចឹម (ប្រាក់កក់សត្វចិញ្ចឹមបង់មុន)",
  ],
  fd_err: [
    "Give a description, an amount above zero and the evidence.",
    "ផ្តល់ការពិពណ៌នា ចំនួនលើសសូន្យ និងភស្តុតាង។",
  ],
  // new: M4 builds the step on the server's records (an inspection, then charges).
  st4_btn: ["Record inspection", "កត់ត្រាការត្រួតពិនិត្យ"],
  st4_fix_btn: ["Correct inspection", "កែការត្រួតពិនិត្យ"],
  st4_date: ["Inspection date", "ថ្ងៃត្រួតពិនិត្យ"],
  st4_date_help: [
    "From the hand-back day ({0}) to today.",
    "ពីថ្ងៃប្រគល់ ({0}) ដល់ថ្ងៃនេះ។",
  ],
  st4_reason: ["Why it is corrected", "ហេតុអ្វីកែ"],
  st4_notes: ["Notes", "កំណត់ចំណាំ"],
  fd_n: ["Finding {0}", "ការរកឃើញ {0}"],
  fd_remove: ["Remove", "ដកចេញ"],
  fd_remove_n: ["Remove finding {0}", "ដកការរកឃើញ {0} ចេញ"],
  fd_amt_help: [
    "Leave the charge and the evidence empty for no charge.",
    "ទុកថ្លៃ និងភស្តុតាងទទេ បើគ្មានថ្លៃ។",
  ],
  st4_ok: ["Save the inspection", "រក្សាទុកការត្រួតពិនិត្យ"],
  st4_ok_charges: ["Save and make the charges", "រក្សាទុក និងបង្កើតថ្លៃ"],
  st4_bad_date: [
    "Choose a day from the hand-back day to today.",
    "ជ្រើសថ្ងៃពីថ្ងៃប្រគល់ ដល់ថ្ងៃនេះ។",
  ],
  st4_bad_reason: [
    "Say why the inspection is corrected.",
    "សូមប្រាប់ហេតុអ្វីកែការត្រួតពិនិត្យ។",
  ],
  st4_bad_desc: [
    "Describe each finding, or remove it.",
    "ពិពណ៌នាការរកឃើញនីមួយៗ ឬដកវាចេញ។",
  ],
  st4_c: [
    "A finding alone charges nothing. Each charge makes a Draft Invoice; a Manager issues it on the Invoices page, due in 7 days.",
    "ការរកឃើញតែឯង មិនគិតថ្លៃទេ។ ថ្លៃនីមួយៗបង្កើតវិក្កយបត្រព្រាង; អ្នកគ្រប់គ្រងចេញវានៅទំព័រវិក្កយបត្រ កំណត់បង់ក្នុង 7 ថ្ងៃ។",
  ],
  st4_c_no_charge: [
    "A finding alone charges nothing. A person allowed to make Damage charges adds the amounts.",
    "ការរកឃើញតែឯង មិនគិតថ្លៃទេ។ អ្នកដែលមានសិទ្ធិគិតថ្លៃខូចខាត បន្ថែមចំនួន។",
  ],
  st4_saved_charge_failed: [
    "The inspection is saved, but a charge was not made. Press Try again; nothing is saved twice.",
    "ការត្រួតពិនិត្យបានរក្សាទុក ប៉ុន្តែថ្លៃមួយមិនទាន់បានបង្កើត។ ចុច ព្យាយាមម្តងទៀត; គ្មានអ្វីរក្សាទុកពីរដងទេ។",
  ],
  st4_saved_charge_refused: [
    "The inspection is saved, but a charge was refused. Check its amount and evidence and save again, or close and use Charge on the finding.",
    "ការត្រួតពិនិត្យបានរក្សាទុក ប៉ុន្តែថ្លៃមួយត្រូវបានបដិសេធ។ ពិនិត្យចំនួន និងភស្តុតាង ហើយរក្សាទុកម្តងទៀត ឬបិទ ហើយប្រើ គិតថ្លៃ លើការរកឃើញ។",
  ],
  st4_charge_btn: ["Charge", "គិតថ្លៃ"],
  st4_charge_t: ["Damage charge", "ថ្លៃខូចខាត"],
  st4_charge_ok: ["Make the charge", "បង្កើតថ្លៃ"],
  st4_charge_c: [
    "Found at the inspection on {0}. The charge makes a Draft Invoice; a Manager issues it on the Invoices page.",
    "រកឃើញនៅការត្រួតពិនិត្យថ្ងៃ {0}។ ថ្លៃបង្កើតវិក្កយបត្រព្រាង; អ្នកគ្រប់គ្រងចេញវានៅទំព័រវិក្កយបត្រ។",
  ],
  st4_no_charge: ["no charge", "គ្មានថ្លៃ"],
  st4_draft: ["Draft", "ព្រាង"],
  st4_open: ["Open", "បើក"],
  st4_clean_rate: [
    "This Parking's cleaning rate: {0}.",
    "អត្រាសម្អាតរបស់ចំណតនេះ៖ {0}។",
  ],
  st4_clean_none: [
    "This Parking has no cleaning rate yet. Set it in Settings, then add the charge.",
    "ចំណតនេះមិនទាន់មានអត្រាសម្អាតទេ។ កំណត់វាក្នុងការកំណត់ ហើយបន្ថែមថ្លៃ។",
  ],
  st4_clean_zero: [
    "This Parking's cleaning rate is zero: no cleaning charge.",
    "អត្រាសម្អាតរបស់ចំណតនេះគឺសូន្យ៖ គ្មានថ្លៃសម្អាត។",
  ],
  st4_clean_hidden: [
    "Your account cannot see the cleaning rate.",
    "គណនីរបស់អ្នកមិនអាចមើលអត្រាសម្អាតបានទេ។",
  ],
  st4_clean_btn: ["Add cleaning charge", "បន្ថែមថ្លៃសម្អាត"],
  st4_clean_c: [
    "Add the cleaning charge of {0} for {1}? It makes a Draft Invoice for {2}.",
    "បន្ថែមថ្លៃសម្អាត {0} សម្រាប់ {1}? វាបង្កើតវិក្កយបត្រព្រាងសម្រាប់ {2}។",
  ],
  st4_drafts_note: [
    "A Draft is not owed yet. A Manager issues it on the Invoices page, due in 7 days.",
    "វិក្កយបត្រព្រាងមិនទាន់ជំពាក់ទេ។ អ្នកគ្រប់គ្រងចេញវានៅទំព័រវិក្កយបត្រ កំណត់បង់ក្នុង 7 ថ្ងៃ។",
  ],
  st4_earlier: [
    "Charges from an earlier inspection",
    "ថ្លៃពីការត្រួតពិនិត្យមុន",
  ],
  st4_reading: [
    "Reading the inspection and the charges…",
    "កំពុងអានការត្រួតពិនិត្យ និងថ្លៃ…",
  ],
  st4_failed: [
    "The inspection or the charges could not be read just now.",
    "មិនអាចអានការត្រួតពិនិត្យ ឬថ្លៃបានទេឥឡូវនេះ។",
  ],
  st4_no_invoices: [
    "Your account cannot see Invoices, so the charges are not shown.",
    "គណនីរបស់អ្នកមិនអាចមើលវិក្កយបត្របានទេ ដូច្នេះថ្លៃមិនបង្ហាញ។",
  ],
  st4_not_allowed: [
    "Your account cannot record the inspection.",
    "គណនីរបស់អ្នកមិនអាចកត់ត្រាការត្រួតពិនិត្យបានទេ។",
  ],
  st4_toast_insp: ["Inspection saved.", "បានរក្សាទុកការត្រួតពិនិត្យ។"],
  st4_toast_drafts: [
    "Saved. Draft Invoices made: {0}.",
    "បានរក្សាទុក។ វិក្កយបត្រព្រាងបានបង្កើត៖ {0}។",
  ],
  st4_toast_draft: [
    "Draft Invoice made for {0}.",
    "បានបង្កើតវិក្កយបត្រព្រាងសម្រាប់ {0}។",
  ],
  st4_other: [
    "This finding was charged before at another amount. Its Draft Invoice bills {0}: correct it on the Invoices page if needed.",
    "ការរកឃើញនេះបានគិតថ្លៃពីមុនក្នុងចំនួនផ្សេង។ វិក្កយបត្រព្រាងរបស់វាគិត {0}: កែវានៅទំព័រវិក្កយបត្រ បើចាំបាច់។",
  ],
  st4_other_some: [
    "Saved, but a charge got no new Draft, or its Draft bills an amount recorded before. Check the Drafts on the Invoices page.",
    "បានរក្សាទុក ប៉ុន្តែថ្លៃមួយមិនបានវិក្កយបត្រព្រាងថ្មី ឬវិក្កយបត្រព្រាងគិតចំនួនដែលកត់ត្រាពីមុន។ ពិនិត្យវិក្កយបត្រព្រាងនៅទំព័រវិក្កយបត្រ។",
  ],
  st4_void: ["Void", "ទុកជាមោឃៈ"],
  st4_two: [
    "More than one inspection is in force for this move-out; the newest is shown. Check the History and the Invoices page.",
    "មានការត្រួតពិនិត្យច្រើនជាងមួយសម្រាប់ការចាកចេញនេះ; បង្ហាញថ្មីបំផុត។ សូមពិនិត្យប្រវត្តិ និងទំព័រវិក្កយបត្រ។",
  ],
  st4_check: [
    "No new Draft was made: the charge may already have its Invoice. The page was read again; check the Invoices page.",
    "មិនបានបង្កើតវិក្កយបត្រព្រាងថ្មីទេ៖ ថ្លៃនេះប្រហែលមានវិក្កយបត្ររួចហើយ។ ទំព័រត្រូវបានអានម្តងទៀត; សូមពិនិត្យទំព័រវិក្កយបត្រ។",
  ],
  st4_clean_other: [
    "The cleaning charge was recorded before at another rate. Its Draft Invoice bills {0}: correct it on the Invoices page if needed.",
    "ថ្លៃសម្អាតបានកត់ត្រាពីមុនក្នុងអត្រាផ្សេង។ វិក្កយបត្រព្រាងរបស់វាគិត {0}: កែវានៅទំព័រវិក្កយបត្រ បើចាំបាច់។",
  ],
  mh_insp: [
    "Move-out inspection: {0} finding(s).",
    "ការត្រួតពិនិត្យពេលចាកចេញ៖ ការរកឃើញ {0}។",
  ],
  mh_insp_fixed: [
    "Inspection corrected: {0} finding(s).",
    "ការត្រួតពិនិត្យត្រូវបានកែ៖ ការរកឃើញ {0}។",
  ],
  // new: why the cleaning charge was refused
  cr_CLEANING_RATE_CHANGED: [
    "The cleaning rate changed meanwhile. Close, check the new rate and add it again.",
    "អត្រាសម្អាតបានផ្លាស់ប្តូរ។ បិទ ពិនិត្យអត្រាថ្មី ហើយបន្ថែមម្តងទៀត។",
  ],
  cr_CLEANING_RATE_NOT_SET: [
    "This Parking has no cleaning rate. Set the rate first.",
    "ចំណតនេះគ្មានអត្រាសម្អាតទេ។ កំណត់អត្រាជាមុនសិន។",
  ],
  cr_CLEANING_RATE_ZERO: [
    "This Parking's cleaning rate is zero, so there is no cleaning charge.",
    "អត្រាសម្អាតរបស់ចំណតនេះគឺសូន្យ ដូច្នេះគ្មានថ្លៃសម្អាត។",
  ],
  cr_CLEANING_CHARGE_NEEDS_MOVE_OUT: [
    "Record the hand-back before the cleaning charge.",
    "កត់ត្រាការប្រគល់មុនថ្លៃសម្អាត។",
  ],
  cr_CLEANING_CHARGE_NOT_MOVED_IN: [
    "There is no cleaning charge, because the Customer never moved in.",
    "គ្មានថ្លៃសម្អាតទេ ព្រោះអតិថិជនមិនដែលចូលនៅ។",
  ],
  cr_elsewhere: [
    "The cleaning charge was recorded another way. Find it on the Invoices page.",
    "ថ្លៃសម្អាតត្រូវបានកត់ត្រាតាមផ្លូវផ្សេង។ រកវានៅទំព័រវិក្កយបត្រ។",
  ],
  // new: a step that saves money records
  c_unknown: [
    "No answer came back. It may or may not be saved: press Try again to send the very same request; nothing is saved twice.",
    "គ្មានចម្លើយត្រឡប់មកវិញ។ វាអាចរក្សាទុក ឬមិនទាន់: ចុច ព្យាយាមម្តងទៀត ដើម្បីផ្ញើសំណើដដែល; គ្មានអ្វីរក្សាទុកពីរដងទេ។",
  ],
  c_refused: [
    "This was not saved. Check the values and try again, or read the page again.",
    "នេះមិនត្រូវបានរក្សាទុកទេ។ ពិនិត្យតម្លៃ ហើយព្យាយាមម្តងទៀត ឬអានទំព័រម្តងទៀត។",
  ],
  st5_t: ["Final Settlement", "ការទូទាត់ចុងក្រោយ"],
  st5_wait: [
    "After the Lease ends and the Parking is handed back.",
    "បន្ទាប់ពីកិច្ចសន្យាបញ្ចប់ និងប្រគល់ចំណត។",
  ],
  st5_todo: [
    "Prepare the statement. Staff prepare the draft; a Manager confirms and closes it.",
    "រៀបចំរបាយការណ៍។ បុគ្គលិករៀបចំសេចក្តីព្រាង; អ្នកគ្រប់គ្រងបញ្ជាក់ និងបិទ។",
  ],
  // new (M5): the Final Settlement step.
  st5_start: ["Start Final Settlement", "ចាប់ផ្តើមការទូទាត់ចុងក្រោយ"],
  // new
  st5_toast: ["Final Settlement started.", "បានចាប់ផ្តើមការទូទាត់ចុងក្រោយ។"],
  // new
  st5_refused: [
    "The Final Settlement could not be started. Read the page again: the Lease may not be terminated yet.",
    "មិនអាចចាប់ផ្តើមការទូទាត់ចុងក្រោយបានទេ។ សូមអានទំព័រម្តងទៀត៖ កិច្ចសន្យាប្រហែលមិនទាន់បញ្ចប់។",
  ],
  // new
  st5_hidden: [
    "You may not see the Final Settlement.",
    "អ្នកមិនអាចមើលការទូទាត់ចុងក្រោយបានទេ។",
  ],
  // new
  st5_failed: [
    "The Final Settlement could not be read.",
    "មិនអាចអានការទូទាត់ចុងក្រោយបានទេ។",
  ],
  // new
  st5_reading: ["Reading the Final Settlement…", "កំពុងអានការទូទាត់ចុងក្រោយ…"],
  // new
  st5_not_allowed: [
    "A person with the Final Settlement right starts it.",
    "អ្នកមានសិទ្ធិការទូទាត់ចុងក្រោយ ជាអ្នកចាប់ផ្តើម។",
  ],
  st5_closed: ["Closed on {0}.", "បានបិទនៅ {0}។"],
  // new
  st5_closed_owed: [
    "{0} stays owed on the Customer Ledger. No write-off in V1.",
    "{0} នៅជំពាក់លើបញ្ជីអតិថិជន។ គ្មានការលុបបំណុលក្នុង V1។",
  ],
  // new
  st5_open: ["Started on {0}.", "បានចាប់ផ្តើមនៅ {0}។"],
  st5_waiting: [
    "A draft waits for a Manager.",
    "សេចក្តីព្រាងរង់ចាំអ្នកគ្រប់គ្រង។",
  ],
  // new
  st5_open_approvals: ["Open Waiting for approval", "បើករង់ចាំការអនុម័ត"],
  // new
  st5_no_preview: [
    "The statement could not be read. Read the page again.",
    "មិនអាចអានរបាយការណ៍បានទេ។ សូមអានទំព័រម្តងទៀត។",
  ],
  st5_statement: ["Statement", "របាយការណ៍"],
  // new
  st5_blocked: ["Not ready yet. First:", "មិនទាន់រួចរាល់ទេ។ ជាមុនសិន៖"],
  // new
  st5_ready: [
    "Ready: the draft can be prepared.",
    "រួចរាល់៖ អាចរៀបចំសេចក្តីព្រាងបាន។",
  ],
  fs_owed: ["Open Invoices and charges", "វិក្កយបត្រ និងថ្លៃនៅជំពាក់"],
  // new
  fs_due: ["Due {0}", "ថ្ងៃកំណត់ {0}"],
  // new
  fs_late: ["Late-payment charge", "ថ្លៃបង់យឺត"],
  // new
  fs_other_customer: ["another Customer", "អតិថិជនផ្សេង"],
  fs_credit: ["Customer Credit", "ឥណទានអតិថិជន"],
  // new
  fs_credit_may: ["Up to {0}", "រហូតដល់ {0}"],
  fs_credit_n: [
    "Own Credit pays own debt first (DL-032).",
    "ឥណទានផ្ទាល់បង់បំណុលផ្ទាល់មុន។",
  ],
  fs_pet_dmg: [
    "Pet Deposit for pet damage",
    "ប្រាក់កក់សត្វចិញ្ចឹម សម្រាប់ខូចខាតដោយសត្វ",
  ],
  // new
  fs_pet_dmg_n: [
    "Pays pet damage first: {0} open.",
    "បង់ការខូចខាតដោយសត្វមុន៖ នៅជំពាក់ {0}។",
  ],
  // new
  fs_sec_n: [
    "Pays all Lease debt, oldest Due Date first.",
    "បង់បំណុលកិច្ចសន្យាទាំងអស់ ថ្ងៃកំណត់ចាស់មុន។",
  ],
  fs_sec_kept: ["Security Deposit kept", "ប្រាក់កក់សុវត្ថិភាពរក្សាទុក"],
  // new
  fs_pet_kept: ["Pet Deposit kept", "ប្រាក់កក់សត្វចិញ្ចឹមរក្សាទុក"],
  // new
  fs_kept_n: [
    "Kept for the termination. Not used for the charges.",
    "រក្សាទុកដោយសារការបញ្ចប់កិច្ចសន្យា។ មិនប្រើសម្រាប់ថ្លៃ។",
  ],
  // new
  fs_kept_first: [
    "The termination keeps it: a Manager records it as kept first.",
    "ការបញ្ចប់កិច្ចសន្យារក្សាវាទុក៖ អ្នកគ្រប់គ្រងកត់ត្រាថារក្សាទុកជាមុនសិន។",
  ],
  // new
  fs_kept_none: [
    "The termination keeps it; it holds nothing.",
    "ការបញ្ចប់កិច្ចសន្យារក្សាវាទុក; គ្មានប្រាក់នៅសល់។",
  ],
  // new (V1-060 B6, DL-106)
  fs_kept_waiting: [
    "The termination keeps it: its draft waits for approval.",
    "ការបញ្ចប់កិច្ចសន្យារក្សាវាទុក៖ សេចក្តីព្រាងរបស់វាកំពុងរង់ចាំការអនុម័ត។",
  ],
  fs_pet_other: [
    "Remaining Pet Deposit for other balance",
    "ប្រាក់កក់សត្វចិញ្ចឹមនៅសល់ សម្រាប់សមតុល្យផ្សេង",
  ],
  fs_pet_other_n: [
    "Only when the Customer asks for it, after the Security Deposit is used up.",
    "តែពេលអតិថិជនស្នើ បន្ទាប់ពីប្រាក់កក់សុវត្ថិភាពអស់។",
  ],
  // new
  fs_pet_other_staff: [
    "When the Customer asks for it, or Staff with a reason, after the Security Deposit is used up.",
    "ពេលអតិថិជនស្នើ ឬបុគ្គលិកដោយមានមូលហេតុ បន្ទាប់ពីប្រាក់កក់សុវត្ថិភាពអស់។",
  ],
  fs_balance: ["Balance and refund", "សមតុល្យ និងការសងវិញ"],
  // new
  fs_later: [
    "Worked out when the draft is prepared.",
    "គណនាពេលរៀបចំសេចក្តីព្រាង។",
  ],
  // new
  fs_voided: [
    "A voided charge is not billed again: {0}.",
    "ថ្លៃដែលបានលុបចោល មិនចេញវិក្កយបត្រម្តងទៀតទេ៖ {0}។",
  ],
  fs_credit_used: ["Customer Credit used", "ឥណទានអតិថិជនបានប្រើ"],
  fs_sec_app: ["Security Deposit applied", "ប្រាក់កក់សុវត្ថិភាពបានប្រើ"],
  fs_balance_owed: ["Balance still owed", "សមតុល្យនៅជំពាក់"],
  fs_refund: ["Refund to the Customer", "សងវិញទៅអតិថិជន"],
  fs_pet_choice: [
    "The Customer asked to use the remaining Pet Deposit for the other balance",
    "អតិថិជនស្នើប្រើប្រាក់កក់សត្វចិញ្ចឹមនៅសល់ សម្រាប់សមតុល្យផ្សេង",
  ],
  pd_t: ["Prepare the Final Settlement", "រៀបចំការទូទាត់ចុងក្រោយ"],
  pd_ok: ["Save draft", "រក្សាទុកសេចក្តីព្រាង"],
  pd_c: [
    "The draft is saved with the statement above. Only a Manager or the Owner can confirm and close it, in Waiting for approval. Nothing moves until then.",
    "សេចក្តីព្រាងរក្សាទុកជាមួយរបាយការណ៍ខាងលើ។ មានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ទេ អាចបញ្ជាក់ និងបិទ នៅរង់ចាំការអនុម័ត។ គ្មានអ្វីផ្លាស់ទី រហូតដល់ពេលនោះ។",
  ],
  pd_toast: [
    "Draft Final Settlement saved. A Manager confirms it in Waiting for approval.",
    "បានរក្សាទុកសេចក្តីព្រាងការទូទាត់ចុងក្រោយ។ អ្នកគ្រប់គ្រងបញ្ជាក់វានៅរង់ចាំការអនុម័ត។",
  ],
  // new
  pd_waiting: [
    "A draft of this Final Settlement already waits for a Manager.",
    "សេចក្តីព្រាងនៃការទូទាត់ចុងក្រោយនេះ កំពុងរង់ចាំអ្នកគ្រប់គ្រងរួចហើយ។",
  ],
  // new
  pd_btn: ["Prepare draft", "រៀបចំសេចក្តីព្រាង"],
  // new
  pd_pet_staff: [
    "Debt is left after the Security Deposit, so the rest of the Pet Deposit pays it before any refund. Say why.",
    "នៅមានបំណុលបន្ទាប់ពីប្រាក់កក់សុវត្ថិភាព ដូច្នេះប្រាក់កក់សត្វចិញ្ចឹមនៅសល់ បង់វាមុនការសងវិញ។ សូមប្រាប់មូលហេតុ។",
  ],
  // new
  pd_basis_customer: ["The Customer asked for it", "អតិថិជនបានស្នើ"],
  // new
  pd_basis_staff: [
    "The Customer will not pay it (staff reason)",
    "អតិថិជននឹងមិនបង់ (មូលហេតុបុគ្គលិក)",
  ],
  // new
  pd_choice: ["Who asked, the date and how", "អ្នកណាស្នើ កាលបរិច្ឆេទ និងរបៀប"],
  // new
  pd_staff: ["Staff reason", "មូលហេតុបុគ្គលិក"],
  cf_method: ["Refund by", "សងវិញដោយ"],
  cf_ref: ["Transfer reference", "លេខយោងផ្ទេរ"],
  // new
  pd_cash_note: ["Paid in cash", "បង់ជាសាច់ប្រាក់"],
  // new
  pd_to: [
    "The refund goes to the Primary Tenant, {0}.",
    "ការសងវិញទៅអ្នកជួលចម្បង {0}។",
  ],
  // new
  pd_no_methods: [
    "No refund method is turned on. The Owner turns one on in Settings, then prepare the draft.",
    "មិនមានវិធីសងវិញដែលបានបើកទេ។ ម្ចាស់បើកវានៅក្នុងការកំណត់ បន្ទាប់មករៀបចំសេចក្តីព្រាងម្តងទៀត។",
  ],
  pd_too_long: [
    "This draft has too many lines to save at once. Record some of the open Payments or Credits first, then prepare it again.",
    "សេចក្តីព្រាងនេះមានបន្ទាត់ច្រើនពេក មិនអាចរក្សាទុកក្នុងពេលតែមួយបានទេ។ សូមកត់ត្រាការបង់ប្រាក់ ឬឥណទានខ្លះជាមុន ហើយរៀបចំម្តងទៀត។",
  ],
  pd_text_long: [
    "The text is too long to save. Shorten the Customer's choice or the staff reason.",
    "អត្ថបទវែងពេក មិនអាចរក្សាទុកបានទេ។ សូមកាត់ខ្លីជម្រើសរបស់អតិថិជន ឬមូលហេតុរបស់បុគ្គលិក។",
  ],
  pd_methods_failed: [
    "The refund methods could not be read. Close and try again.",
    "មិនអាចអានវិធីសងវិញបានទេ។ សូមបិទ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  pd_reason: ["Reason", "មូលហេតុ"],
  // new
  pd_reason_default: [
    "Final Settlement prepared from the move-out",
    "ការទូទាត់ចុងក្រោយរៀបចំពីការចាកចេញ",
  ],
  // new
  pd_err: [
    "Fill in every box marked Required. A bank transfer needs its reference.",
    "សូមបំពេញប្រអប់ដែលចាំបាច់ទាំងអស់។ ការផ្ទេរធនាគារត្រូវមានលេខយោង។",
  ],
  // new (V1-060 B6, DL-106): Record kept Deposit on the Final Settlement step.
  kd_btn_SECURITY: [
    "Record kept Security Deposit",
    "កត់ត្រាប្រាក់កក់សុវត្ថិភាពដែលរក្សាទុក",
  ],
  kd_btn_PET: [
    "Record kept Pet Deposit",
    "កត់ត្រាប្រាក់កក់សត្វចិញ្ចឹមដែលរក្សាទុក",
  ],
  manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  kd_deposit: ["Deposit", "ប្រាក់កក់"],
  kd_amount: ["Amount kept", "ចំនួនរក្សាទុក"],
  kd_all: ["{0}, all it holds", "{0} ទាំងអស់ដែលមាន"],
  kd_why: ["Why it is kept", "មូលហេតុរក្សាទុក"],
  kd_g_early: [
    "The Lease ended before its End Date.",
    "កិច្ចសន្យាបានបញ្ចប់មុនថ្ងៃបញ្ចប់។",
  ],
  kd_g_pet: ["The pet rules were broken.", "ច្បាប់សត្វចិញ្ចឹមត្រូវបានបំពាន។"],
  kd_g_initial: [
    "The Initial Rent was not paid.",
    "ថ្លៃជួលដំបូងមិនត្រូវបានបង់។",
  ],
  kd_g_broken: ["The Customer broke the Lease.", "អតិថិជនបានបំពានកិច្ចសន្យា។"],
  kd_g_default: [
    "The Rent was not paid for 30 days.",
    "ថ្លៃជួលមិនត្រូវបានបង់អស់រយៈពេល 30 ថ្ងៃ។",
  ],
  kd_g_other: [
    "The termination of the Lease keeps it.",
    "ការបញ្ចប់កិច្ចសន្យារក្សាវាទុក។",
  ],
  kd_reason_default: [
    "Deposit kept at move-out. {0}",
    "ប្រាក់កក់រក្សាទុកពេលចាកចេញ។ {0}",
  ],
  kd_note: [
    "This saves a draft. Nothing is kept until the Owner or a Manager approves it in Waiting for approval. Then prepare the Final Settlement.",
    "នេះរក្សាទុកសេចក្តីព្រាង។ គ្មានអ្វីត្រូវបានរក្សាទុកទេ រហូតដល់ម្ចាស់ ឬអ្នកគ្រប់គ្រងអនុម័តវា នៅរង់ចាំការអនុម័ត។ បន្ទាប់មក រៀបចំការទូទាត់ចុងក្រោយ។",
  ],
  kd_err: ["Write the reason.", "សូមសរសេរមូលហេតុ។"],
  kd_toast: [
    "Draft saved: keep the {0}. The Owner or a Manager approves it in Waiting for approval.",
    "បានរក្សាទុកសេចក្តីព្រាង៖ រក្សាទុក{0}។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងអនុម័តវា នៅរង់ចាំការអនុម័ត។",
  ],
  kd_waiting: [
    "A draft that keeps this Deposit already waits for approval.",
    "សេចក្តីព្រាងដែលរក្សាប្រាក់កក់នេះ កំពុងរង់ចាំការអនុម័តរួចហើយ។",
  ],
  kd_r_DEPOSIT_FORFEITURE_NO_GROUND: [
    "The end of this Lease does not keep this Deposit. Read the page again.",
    "ការបញ្ចប់កិច្ចសន្យានេះ មិនរក្សាប្រាក់កក់នេះទុកទេ។ សូមអានទំព័រម្តងទៀត។",
  ],
  kd_r_DEPOSIT_FORFEITURE_LEASE_NOT_TERMINATED: [
    "The Lease has not ended, so the Deposit cannot be kept yet.",
    "កិច្ចសន្យាមិនទាន់បញ្ចប់ទេ ដូច្នេះមិនអាចរក្សាប្រាក់កក់ទុកបានទេ។",
  ],
  kd_r_DEPOSIT_FORFEITURE_NOTHING_HELD: [
    "This Deposit holds no money to keep. Read the page again.",
    "ប្រាក់កក់នេះគ្មានប្រាក់ត្រូវរក្សាទុកទេ។ សូមអានទំព័រម្តងទៀត។",
  ],
  kd_r_DEPOSIT_FORFEITURE_PET_AT_SETTLEMENT: [
    "This Pet Deposit is decided in the Final Settlement, not kept here.",
    "ប្រាក់កក់សត្វចិញ្ចឹមនេះ សម្រេចក្នុងការទូទាត់ចុងក្រោយ មិនមែនរក្សាទុកនៅទីនេះទេ។",
  ],
  kd_r_FINAL_SETTLEMENT_CLOSED: [
    "The Final Settlement is closed. A change now needs a correction after closure.",
    "ការទូទាត់ចុងក្រោយបានបិទហើយ។ ការផ្លាស់ប្តូរឥឡូវត្រូវការការកែតម្រូវបន្ទាប់ពីបិទ។",
  ],
  kd_r_DRAFT_RECORD_ID_IN_USE: [
    "This form was used before. Close it, then open it again.",
    "ទម្រង់នេះត្រូវបានប្រើរួចហើយ។ សូមបិទវា ហើយបើកម្តងទៀត។",
  ],
  // new: what blocks the Final Settlement (the preview's blocking issues).
  fi_FINAL_UTILITY_NOT_ISSUED: [
    "Issue the final Utility Invoice (step 3).",
    "ចេញវិក្កយបត្រទឹកភ្លើងចុងក្រោយ (ជំហាន 3)។",
  ],
  fi_UTILITY_PERIOD_NOT_BILLED: [
    "Bill every Utility period of the Lease.",
    "ចេញវិក្កយបត្ររយៈពេលទឹកភ្លើងទាំងអស់នៃកិច្ចសន្យា។",
  ],
  fi_CLEANING_CHARGE_MISSING: [
    "Record the cleaning charge (step 4).",
    "កត់ត្រាថ្លៃសម្អាត (ជំហាន 4)។",
  ],
  fi_LATE_PAYMENT_DECISION_MISSING: [
    "Decide the late-payment charges of the Lease.",
    "សម្រេចថ្លៃបង់យឺតនៃកិច្ចសន្យា។",
  ],
  fi_FORFEITURE_NOT_CONFIRMED: [
    "A Manager records the kept Deposit.",
    "អ្នកគ្រប់គ្រងកត់ត្រាប្រាក់កក់ដែលរក្សាទុក។",
  ],
  // new (V1-060 B6, DL-106): the kept-Deposit draft is recorded and waits.
  fi_FORFEITURE_WAITING: [
    "The Owner or a Manager approves the kept Deposit in Waiting for approval.",
    "ម្ចាស់ ឬអ្នកគ្រប់គ្រងអនុម័តប្រាក់កក់ដែលរក្សាទុក នៅរង់ចាំការអនុម័ត។",
  ],
  fi_PENDING_DRAFT: [
    "Wait for the draft that waits for a Manager.",
    "រង់ចាំសេចក្តីព្រាងដែលកំពុងរង់ចាំអ្នកគ្រប់គ្រង។",
  ],
  fi_ONE_TIME_CHARGE_NOT_INVOICED: [
    "Make the Invoice of each recorded charge (step 4).",
    "ធ្វើវិក្កយបត្រនៃថ្លៃដែលបានកត់ត្រានីមួយៗ (ជំហាន 4)។",
  ],
  fi_INVOICE_DRAFT_NOT_ISSUED: [
    "Issue or remove the draft Invoices of the Lease.",
    "ចេញ ឬដកវិក្កយបត្រព្រាងនៃកិច្ចសន្យាចេញ។",
  ],
  fi_OTHER: [
    "Something else blocks it. Read the page again later.",
    "មានអ្វីផ្សេងរារាំង។ សូមអានទំព័រម្តងទៀតពេលក្រោយ។",
  ],
  st6_t: ["After closure", "បន្ទាប់ពីបិទ"],
  // new (V1-060 B6)
  st6_finished: [
    "The move-out is finished. Use this step only if something comes up later.",
    "ការចាកចេញបានបញ្ចប់។ ប្រើជំហាននេះ តែពេលមានអ្វីកើតឡើងនៅពេលក្រោយ។",
  ],
  st6_note: [
    "A closed Final Settlement is never reopened. A later charge or refund is a linked correction with a reason, confirmed by a Manager.",
    "ការទូទាត់ចុងក្រោយបានបិទ មិនបើកឡើងវិញទេ។ ថ្លៃ ឬការសងវិញក្រោយ ជាការកែភ្ជាប់ដោយមានមូលហេតុ បញ្ជាក់ដោយអ្នកគ្រប់គ្រង។",
  ],
  st6_charge: ["Add a charge", "បន្ថែមថ្លៃ"],
  st6_not_allowed: [
    "Only people who prepare Final Settlements add a charge here.",
    "មានតែអ្នករៀបចំការទូទាត់ចុងក្រោយទេ ដែលអាចបន្ថែមថ្លៃនៅទីនេះ។",
  ],
  st6_refund_later: [
    "A refund after closure comes in a later update.",
    "ការសងវិញក្រោយបិទ នឹងមកក្នុងការធ្វើបច្ចុប្បន្នភាពក្រោយ។",
  ],
  st6_approvals: [
    "Corrections waiting: Waiting for approval",
    "ការកែដែលកំពុងរង់ចាំ៖ រង់ចាំការអនុម័ត",
  ],
  st6_toast: [
    "Saved as a draft. A Manager confirms it in Waiting for approval.",
    "បានរក្សាទុកជាសេចក្តីព្រាង។ អ្នកគ្រប់គ្រងបញ្ជាក់វានៅក្នុង រង់ចាំការអនុម័ត។",
  ],
  c6_ok: ["Save draft", "រក្សាទុកសេចក្តីព្រាង"],
  c6_kind: ["Charge for", "ថ្លៃសម្រាប់"],
  c6_misc: ["Something else", "ផ្សេងទៀត"],
  c6_damage: ["Damage: {0}", "ការខូចខាត៖ {0}"],
  c6_what: ["What it is for", "សម្រាប់អ្វី"],
  c6_reason: ["Reason", "មូលហេតុ"],
  c6_err: [
    "Fill in every box marked Required.",
    "សូមបំពេញប្រអប់ដែលចាំបាច់ទាំងអស់។",
  ],
  c6_c: [
    "{0} is charged on a new Invoice once a Manager confirms it. The closed Final Settlement stays as it is.",
    "{0} ត្រូវបានគិតថ្លៃលើវិក្កយបត្រថ្មី នៅពេលអ្នកគ្រប់គ្រងបញ្ជាក់។ ការទូទាត់ចុងក្រោយដែលបានបិទ នៅដដែល។",
  ],
  deps_t: ["Deposits", "ប្រាក់កក់"],
  dep_SECURITY: ["Security Deposit", "ប្រាក់កក់សុវត្ថិភាព"],
  dep_PET: ["Pet Deposit", "ប្រាក់កក់សត្វចិញ្ចឹម"],
  dep_held: ["{0} held", "កាន់កាប់ {0}"],
  // new
  dep_received: ["received {0}", "បានទទួល {0}"],
  dep_none: [
    "No Pet Deposit on this Lease.",
    "គ្មានប្រាក់កក់សត្វចិញ្ចឹមលើកិច្ចសន្យានេះ។",
  ],
  // new
  dep_hidden: [
    "Your account cannot see Deposits.",
    "គណនីរបស់អ្នកមិនអាចមើលប្រាក់កក់បានទេ។",
  ],
  // new
  dep_failed: [
    "The Deposits could not be read just now.",
    "មិនអាចអានប្រាក់កក់បានទេឥឡូវនេះ។",
  ],
  history_t: ["History", "ប្រវត្តិ"],
  h_none: ["Nothing recorded yet.", "មិនទាន់មានកំណត់ត្រា។"],
  mh_hb: [
    "Handed back on {0}; Parking set to {1}.",
    "បានប្រគល់នៅ {0}; ចំណតត្រូវបានកំណត់ជា {1}។",
  ],
  // new
  mh_hb_fixed: [
    "Hand-back corrected: {0}; Parking {1}.",
    "ការប្រគល់ត្រូវបានកែ៖ {0}; ចំណត {1}។",
  ],
  open_lease: ["Open Lease", "បើកកិច្ចសន្យា"],
  open_unit: ["Open Parking", "បើកចំណត"],
  back: ["Move-out", "ការចាកចេញ"],
  loading: ["Reading the move-outs…", "កំពុងអានការចាកចេញ…"],
  failed: [
    "The move-outs could not be read just now. Check the connection and try again.",
    "មិនអាចអានការចាកចេញបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],
  missing: [
    "This Lease has no move-out to show, or your account cannot see it.",
    "កិច្ចសន្យានេះគ្មានការចាកចេញត្រូវបង្ហាញ ឬគណនីរបស់អ្នកមិនអាចមើលវាបានទេ។",
  ],
  no_property: [
    "This screen needs the Property. Open Settings and load it first.",
    "អេក្រង់នេះត្រូវការអគារ។ បើកការកំណត់ ហើយផ្ទុកវាជាមុនសិន។",
  ],
  close: ["Close", "បិទ"],
  saving: ["Saving…", "កំពុងរក្សាទុក…"],
  try_again: ["Try again", "ព្យាយាមម្តងទៀត"],
  unknown: [
    "No answer came back. The hand-back may or may not be saved: press Try again to send the very same request.",
    "គ្មានចម្លើយត្រឡប់មកវិញ។ ការប្រគល់អាចរក្សាទុក ឬមិនទាន់: ចុច ព្យាយាមម្តងទៀត ដើម្បីផ្ញើសំណើដដែល។",
  ],
  refused: [
    "The hand-back was not saved. Check the date and try again, or read the Lease again.",
    "ការប្រគល់មិនត្រូវបានរក្សាទុកទេ។ ពិនិត្យថ្ងៃ ហើយព្យាយាមម្តងទៀត ឬអានកិច្ចសន្យាម្តងទៀត។",
  ],
  conflict: [
    "The Lease or the Parking changed meanwhile. The page was read again; check it and record again.",
    "កិច្ចសន្យា ឬចំណតបានផ្លាស់ប្តូរ។ ទំព័រត្រូវបានអានម្តងទៀត; សូមពិនិត្យ ហើយកត់ត្រាម្តងទៀត។",
  ],
  required: ["required", "ត្រូវការ"],
  // new
  records: ["Earlier Deposit forms", "ទម្រង់ប្រាក់កក់ពីមុន"],
  // new
  records_note: [
    "In English, until the Final Settlement steps replace them.",
    "ជាភាសាអង់គ្លេស រហូតដល់ជំហានការទូទាត់ចុងក្រោយជំនួសវា។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type MoveOutTextKey = keyof typeof TEXT;

/** The words for `key`, with {0}, {1} … filled in. */
export function mt(
  language: Language,
  key: MoveOutTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "km" ? 1 : 0];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

export function conditionText(language: Language, condition: string): string {
  const key = `cond_${condition}`;
  return key in TEXT
    ? mt(language, key as MoveOutTextKey)
    : condition.toLowerCase().replace(/_/g, " ");
}

/** Why a final reading step was refused, from the server's stable reason code. An unknown code
 *  says only that nothing was saved: the hand-back itself is saved before this step. */
export function utilityRefusalText(language: Language, code: string): string {
  const key = `ur_${code}`;
  return key in TEXT
    ? mt(language, key as MoveOutTextKey)
    : mt(language, "c_refused");
}
