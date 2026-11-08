// Telegram bots step 2c (DL-128): the words of Office › Telegram, Linked tenants and Telegram
// health, step 2d part 2 (DL-170): Contact office and FAQ, and step 3a (DL-171): Bookings ›
// Visit requests, in English and Khmer, from the mock-up round 29 (i18n34.js, keys tg_*) and
// earlier rounds. Khmer marked "new" is not in the mock-up and needs the native check.

import type { Language } from "../signInText";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: ["This could not be read just now.", "មិនអាចអានបានទេឥឡូវនេះ។"],
  retry_read: ["Try again", "សាកម្តងទៀត"],
  no_property: ["Choose a Property first.", "សូមជ្រើសអចលនទ្រព្យជាមុន។"],
  cancel: ["Cancel", "បោះបង់"],
  hours: ["{0} hours", "{0} ម៉ោង"],
  e_403: [
    "You do not have the right to do this.",
    // new
    "អ្នកមិនមានសិទ្ធិធ្វើការនេះទេ។",
  ],
  e_save: [
    "This could not be saved just now. Try again.",
    // new
    "មិនអាចរក្សាទុកបានទេឥឡូវនេះ។ សូមសាកម្តងទៀត។",
  ],
  // Linked tenants
  links_sub: [
    "Tenant bot accounts linked to a Lease. A link ends by itself when the Lease ends.",
    "គណនីបូតអ្នកជួលដែលភ្ជាប់នឹងកិច្ចសន្យា។ ការភ្ជាប់បញ្ចប់ដោយខ្លួនឯង ពេលកិច្ចសន្យាបញ្ចប់។",
  ],
  linked_now: ["Linked now", "កំពុងភ្ជាប់"],
  c_acc: ["Telegram account", "គណនីតេឡេក្រាម"],
  c_cust: ["Customer", "អតិថិជន"],
  c_unit: ["Unit", "បន្ទប់"],
  c_lease_end: [
    "Lease ends",
    // new
    "កិច្ចសន្យាបញ្ចប់",
  ],
  c_on: ["Linked on", "ភ្ជាប់នៅ"],
  c_how: ["How", "របៀប"],
  how: ["Phone, name and Unit matched", "ទូរស័ព្ទ ឈ្មោះ និងបន្ទប់ត្រូវគ្នា"],
  remove: ["Remove link", "ដកការភ្ជាប់"],
  links_n: [
    "A link needs the phone, the name and the Unit to match an active Lease. There is no code. Several people on one Lease can each link.",
    "ការភ្ជាប់ត្រូវការទូរស័ព្ទ ឈ្មោះ និងបន្ទប់ ត្រូវនឹងកិច្ចសន្យាសកម្ម។ គ្មានលេខកូដ។ មនុស្សច្រើននាក់ក្នុងកិច្ចសន្យាតែមួយ អាចភ្ជាប់ម្នាក់ៗ។",
  ],
  none_linked: [
    "No tenant is linked yet.",
    // new
    "មិនទាន់មានអ្នកជួលភ្ជាប់នៅឡើយទេ។",
  ],
  tries_t: [
    "Link tries that did not match: {0} Telegram accounts.",
    "ការភ្ជាប់មិនត្រូវ៖ គណនីតេឡេក្រាម {0}។",
  ],
  tries_h: ["Link tries that did not match", "ការភ្ជាប់ដែលមិនត្រូវ"],
  c_phone: ["Phone", "ទូរស័ព្ទ"],
  c_name: ["Name typed", "ឈ្មោះដែលវាយ"],
  c_unit_t: ["Unit typed", "បន្ទប់ដែលវាយ"],
  c_tries: ["Tries", "ចំនួនដង"],
  c_last: [
    "Last try",
    // new
    "ការព្យាយាមចុងក្រោយ",
  ],
  blocked: ["Blocked until {0}", "បិទរហូតដល់ {0}"],
  left: ["{0} tries left", "នៅសល់ {0} ដង"],
  tries_n: [
    "The bot never says which part was wrong. {0} failed tries block linking for {1}. Tries are kept 90 days.",
    "បូតមិនដែលប្រាប់ថាផ្នែកណាខុសទេ។ ខុស {0} ដង បិទការភ្ជាប់ {1}។ រក្សាទុកការព្យាយាម ៩០ ថ្ងៃ។",
  ],
  none_tries: [
    "No link tries failed in the last 24 hours.",
    // new
    "គ្មានការភ្ជាប់មិនត្រូវក្នុង ២៤ ម៉ោងចុងក្រោយទេ។",
  ],
  ended: ["Ended links", "ការភ្ជាប់ដែលបានបញ្ចប់"],
  ended_sub: [
    "The last {0} days.",
    // new
    "{0} ថ្ងៃចុងក្រោយ។",
  ],
  c_end: ["Ended on", "បញ្ចប់នៅ"],
  c_why: ["Why", "ហេតុអ្វី"],
  end_LEASE_ENDED: ["The Lease ended", "កិច្ចសន្យាបានបញ្ចប់"],
  end_REMOVED: [
    "Removed by the office",
    // new
    "ដកចេញដោយការិយាល័យ",
  ],
  end_NEW_LINK: [
    "A new link took its place",
    // new
    "ការភ្ជាប់ថ្មីបានជំនួស",
  ],
  none_ended: [
    "No link ended in this time.",
    // new
    "គ្មានការភ្ជាប់បានបញ្ចប់ក្នុងរយៈពេលនេះទេ។",
  ],
  rm_t: ["Remove link", "ដកការភ្ជាប់"],
  rm_q: [
    "Remove the Telegram link of {0} ({1}, {2})? The Tenant bot then shows only Link my Lease.",
    "ដកការភ្ជាប់តេឡេក្រាមរបស់ {0} ({1}, {2})? បន្ទាប់មក បូតអ្នកជួលបង្ហាញតែ ភ្ជាប់កិច្ចសន្យារបស់ខ្ញុំ។",
  ],
  rm_reason: ["Reason", "មូលហេតុ"],
  rm_ph: [
    "For example: lost phone, or wrong person",
    "ឧទាហរណ៍៖ បាត់ទូរស័ព្ទ ឬមនុស្សខុស",
  ],
  rm_n: [
    "It stops working in the bot within a minute. The link stays in the history.",
    "វាឈប់ដំណើរការក្នុងបូតក្នុងមួយនាទី។ ការភ្ជាប់នៅក្នុងប្រវត្តិ។",
  ],
  rm_done: ["Link of {0} removed.", "បានដកការភ្ជាប់របស់ {0}។"],
  e_reason: [
    "Type a reason.",
    // new
    "សូមវាយមូលហេតុ។",
  ],
  e_rm_409: [
    "This link has already ended. The list is read again.",
    // new
    "ការភ្ជាប់នេះបានបញ្ចប់រួចហើយ។ បញ្ជីត្រូវបានអានម្ដងទៀត។",
  ],
  // Telegram health
  h_sub: [
    "Is everything going in and out? The app pulls from the relay every minute.",
    "តើអ្វីៗចូល និងចេញបានល្អទេ? កម្មវិធីទាញពីរ៉េឡេរៀងរាល់មួយនាទី។",
  ],
  h_lock: [
    "Only the Owner and the Manager see this page.",
    "មានតែម្ចាស់ និងអ្នកគ្រប់គ្រងទេដែលឃើញទំព័រនេះ។",
  ],
  k_pull: ["Last relay pull", "ការទាញពីរ៉េឡេចុងក្រោយ"],
  k_pull_s: ["{0} items saved", "បានរក្សាទុក {0}"],
  k_pull_none: [
    "Not pulled yet",
    // new
    "មិនទាន់បានទាញទេ",
  ],
  k_wait: ["Waiting to send", "រង់ចាំផ្ញើ"],
  k_wait_s: [
    "The app tries again by itself",
    "កម្មវិធីព្យាយាមម្ដងទៀតដោយខ្លួនឯង",
  ],
  k_bad: ["Failed to send", "ផ្ញើមិនបាន"],
  k_bad_s: ["Failing for 12 hours or more", "មិនបានជាង ១២ ម៉ោង"],
  k_old: ["Not pulled after 7 days", "មិនបានទាញក្រោយ ៧ ថ្ងៃ"],
  k_old_s: [
    "The relay deletes them; check if above 0",
    "រ៉េឡេលុបវាចោល សូមពិនិត្យបើលើសពី ០",
  ],
  last_err: ["Last error at {0}: {1}.", "កំហុសចុងក្រោយនៅ {0}៖ {1}។"],
  bots: ["Bots", "បូត"],
  c_bot: ["Bot", "បូត"],
  c_in: ["Last message in", "សារចូលចុងក្រោយ"],
  c_out: ["Last message out", "សារចេញចុងក្រោយ"],
  c_state: [
    "State",
    // new
    "ស្ថានភាព",
  ],
  working: ["Working", "ដំណើរការ"],
  problem: ["Problem", "មានបញ្ហា"],
  never: [
    "Never",
    // new
    "មិនដែល",
  ],
  bot_CUSTOMER: [
    "Customer bot",
    // new
    "បូតអតិថិជន",
  ],
  bot_TENANT: [
    "Tenant bot",
    // new
    "បូតអ្នកជួល",
  ],
  bot_STAFF: [
    "Staff bot",
    // new
    "បូតបុគ្គលិក",
  ],
  keys: [
    "No bot keys are ever shown here. The keys are files on the office computer, never in the app, a log or a screenshot.",
    "មិនដែលបង្ហាញសោបូតនៅទីនេះទេ។ សោជាឯកសារនៅលើកុំព្យូទ័រការិយាល័យ មិនដែលនៅក្នុងកម្មវិធី កំណត់ហេតុ ឬរូបថតអេក្រង់ឡើយ។",
  ],
  outbox: ["Messages not sent yet", "សារមិនទាន់ផ្ញើ"],
  c_to: ["To", "ទៅ"],
  c_since: ["Since", "តាំងពី"],
  c_err: ["Last error", "កំហុសចុងក្រោយ"],
  to_chat: [
    "Telegram chat",
    // new
    "ការជជែកតេឡេក្រាម",
  ],
  st_WAITING: [
    "The app tries again",
    // new
    "កម្មវិធីកំពុងព្យាយាមម្ដងទៀត",
  ],
  st_GAVE_UP: [
    "Stopped after 7 days",
    // new
    "បានឈប់ក្រោយ ៧ ថ្ងៃ",
  ],
  retried: [
    "Sent again",
    // new
    "បានផ្ញើម្ដងទៀត",
  ],
  retry: ["Retry", "ព្យាយាមម្ដងទៀត"],
  retry_done: [
    "{0}: the message waits to be sent again. It goes out within a minute.",
    // new
    "{0}៖ សាររង់ចាំផ្ញើម្ដងទៀត។ វានឹងចេញក្នុងមួយនាទី។",
  ],
  e_retry_409: [
    "This message was already sent again, or it is still being tried. The list is read again.",
    // new
    "សារនេះបានផ្ញើម្ដងទៀតរួចហើយ ឬកំពុងព្យាយាមនៅឡើយ។ បញ្ជីត្រូវបានអានម្ដងទៀត។",
  ],
  outbox_n: [
    "Every message waits in the outbox first, so nothing is lost if Telegram is slow.",
    "សារនីមួយៗរង់ចាំក្នុងប្រអប់ចេញជាមុន ដូច្នេះគ្មានអ្វីបាត់ទេ បើតេឡេក្រាមយឺត។",
  ],
  none_outbox: [
    "Every message was sent.",
    // new
    "សារទាំងអស់បានផ្ញើរួចហើយ។",
  ],
  err_telegram_blocked_by_person: [
    "The person blocked the bot",
    "អ្នកនោះបានបិទបូត",
  ],
  err_telegram_unreachable: [
    "Telegram did not answer in time",
    "តេឡេក្រាមមិនឆ្លើយទាន់ពេល",
  ],
  err_telegram_too_many: [
    "Telegram asked the app to slow down",
    // new
    "តេឡេក្រាមសុំឱ្យកម្មវិធីផ្ញើយឺតបន្តិច",
  ],
  err_relay_unreachable: [
    "The relay did not answer; tried again next minute",
    "រ៉េឡេមិនឆ្លើយ ហើយបានព្យាយាមម្ដងទៀតនៅនាទីបន្ទាប់",
  ],
  pulls: ["Last relay pulls", "ការទាញពីរ៉េឡេចុងក្រោយ"],
  c_at: ["Time", "ម៉ោង"],
  c_items: ["Items", "ចំនួន"],
  c_res: ["Result", "លទ្ធផល"],
  pull_OK: ["OK", "ល្អ"],
  pull_FAILED: [
    "Failed",
    // new
    "មិនបាន",
  ],
  none_pulls: [
    "The app has not pulled from the relay yet.",
    // new
    "កម្មវិធីមិនទាន់បានទាញពីរ៉េឡេនៅឡើយទេ។",
  ],
  // Contact office (mock-up tg_inbox_*, tg_reply, tg_called)
  contact_sub: [
    "Messages from the Customer bot and the Tenant bot. Oldest first.",
    "សារពីបូតអតិថិជន និងបូតអ្នកជួល។ ចាស់មុន។",
  ],
  contact_n: [
    "Customer service replies Monday to Saturday, 07:00 to 17:00. A reply goes out through the same bot.",
    "ផ្នែកបម្រើអតិថិជនឆ្លើយពីថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង ០៧:០០ ដល់ ១៧:០០។ ការឆ្លើយតបផ្ញើតាមបូតដដែល។",
  ],
  ib_NEW: ["Waiting", "កំពុងរង់ចាំ"],
  ib_DONE: ["Answered", "បានឆ្លើយ"],
  c_from: ["From", "ពី"],
  c_msg: ["Message", "សារ"],
  reply: ["Reply", "ឆ្លើយតប"],
  called: ["Answered by phone", "បានឆ្លើយតាមទូរស័ព្ទ"],
  send: ["Send", "ផ្ញើ"],
  save: [
    "Save",
    // new
    "រក្សាទុក",
  ],
  rep_l: ["Your reply", "ការឆ្លើយតបរបស់អ្នក"],
  call_l: ["What you said on the phone", "អ្វីដែលអ្នកបាននិយាយតាមទូរស័ព្ទ"],
  rep_n: [
    "Sent by the {0}. Kept in the history.",
    "ផ្ញើដោយ{0}។ រក្សាទុកក្នុងប្រវត្តិ។",
  ],
  call_n: [
    "Nothing is sent. The note is kept in the history.",
    "មិនផ្ញើអ្វីទេ។ កំណត់ចំណាំរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  rep_done: ["Reply sent to {0}.", "បានផ្ញើការឆ្លើយតបទៅ {0}។"],
  call_done: ["{0}: saved.", "{0}៖ បានរក្សាទុក។"],
  ans_TELEGRAM: ["Replied by {0}, {1}", "ឆ្លើយដោយ {0}, {1}"],
  ans_PHONE: ["Phoned by {0}, {1}", "ទូរស័ព្ទដោយ {0}, {1}"],
  e_text: ["Please write this.", "សូមសរសេរ។"],
  none_waiting: [
    "No message is waiting.",
    // new
    "គ្មានសាររង់ចាំទេ។",
  ],
  none_answered: [
    "No message was answered in the last 90 days.",
    // new
    "គ្មានសារដែលបានឆ្លើយក្នុងរយៈពេល ៩០ ថ្ងៃចុងក្រោយទេ។",
  ],
  e_answered: [
    "Someone already answered this message. The list was read again.",
    // new
    "មានគេបានឆ្លើយសារនេះរួចហើយ។ បញ្ជីត្រូវបានអានម្ដងទៀត។",
  ],
  // FAQ (mock-up tg_faq_*)
  faq_sub: [
    "Questions and answers the bots show, in Khmer and English.",
    "សំណួរ និងចម្លើយដែលបូតបង្ហាញ ជាភាសាខ្មែរ និងអង់គ្លេស។",
  ],
  faq_new: ["New question", "សំណួរថ្មី"],
  faq_pend: [
    "New version from {0} waits for the Owner",
    "កំណែថ្មីពី {0} រង់ចាំម្ចាស់",
  ],
  faq_ok: ["Approve", "អនុម័ត"],
  faq_see: ["See the new version", "មើលកំណែថ្មី"],
  faq_n: [
    "The bots show only the version the Owner approved. Each change is a new version.",
    "បូតបង្ហាញតែកំណែដែលម្ចាស់អនុម័ត។ ការប្ដូរនីមួយៗជាកំណែថ្មី។",
  ],
  faq_ed: ["Edit question {0}", "កែសំណួរ {0}"],
  q_en: ["Question in English", "សំណួរជាភាសាអង់គ្លេស"],
  a_en: ["Answer in English", "ចម្លើយជាភាសាអង់គ្លេស"],
  q_km: ["Question in Khmer", "សំណួរជាភាសាខ្មែរ"],
  a_km: ["Answer in Khmer", "ចម្លើយជាភាសាខ្មែរ"],
  faq_own_n: [
    "You are the Owner: the bots use this version as soon as you save.",
    "អ្នកជាម្ចាស់៖ បូតប្រើកំណែនេះភ្លាមពេលអ្នករក្សាទុក។",
  ],
  faq_mgr_n: [
    "The bots keep the old version until the Owner approves this one.",
    "បូតរក្សាកំណែចាស់ រហូតដល់ម្ចាស់អនុម័តកំណែនេះ។",
  ],
  faq_save_ok: ["Save and use", "រក្សាទុក និងប្រើ"],
  faq_save: ["Send to the Owner", "ផ្ញើទៅម្ចាស់"],
  faq_done_ok: [
    "Question {0}: the bots use the new version.",
    "សំណួរ {0}៖ បូតប្រើកំណែថ្មី។",
  ],
  faq_done: [
    "Question {0}: sent to the Owner to approve.",
    "សំណួរ {0}៖ បានផ្ញើទៅម្ចាស់ដើម្បីអនុម័ត។",
  ],
  c_no: ["No.", "ល.រ"],
  c_q: ["Question", "សំណួរ"],
  c_who: ["Who sees it", "អ្នកឃើញ"],
  c_ver: ["Version", "កំណែ"],
  ver: ["Version {0}", "កំណែ {0}"],
  ok_by: ["Approved by {0}, {1}", "អនុម័តដោយ {0}, {1}"],
  who_BOTH: ["Customers and tenants", "អតិថិជន និងអ្នកជួល"],
  who_CUSTOMER: ["Customers", "អតិថិជន"],
  who_TENANT: ["Tenants", "អ្នកជួល"],
  who_HIDDEN: [
    "Hidden: no bot shows it",
    // new
    "លាក់៖ គ្មានបូតណាបង្ហាញទេ",
  ],
  not_yet: [
    "Not approved yet",
    // new
    "មិនទាន់អនុម័ត",
  ],
  edit: ["Edit", "កែ"],
  none_faq: [
    "No questions yet. The bots say there are no questions and offer Contact office.",
    // new
    "មិនទាន់មានសំណួរទេ។ បូតប្រាប់ថាមិនទាន់មានសំណួរ ហើយណែនាំឱ្យទាក់ទងការិយាល័យ។",
  ],
  // new: DL-179.
  faq_starter: ["Load the 15 starter questions", "ផ្ទុកសំណួរចាប់ផ្តើម ១៥"],
  faq_starter_sub: [
    "The questions from the FAQ draft. Each waits for the Owner to approve it before a bot shows it.",
    "សំណួរពីសេចក្តីព្រាង FAQ។ សំណួរនីមួយៗរង់ចាំម្ចាស់អនុម័ត មុនពេលបូតបង្ហាញ។",
  ],
  faq_starter_done: [
    "15 questions loaded. Each waits for the Owner to approve it.",
    "បានផ្ទុកសំណួរ ១៥។ សំណួរនីមួយៗរង់ចាំម្ចាស់អនុម័ត។",
  ],
  faq_read_only: [
    "Only the Owner and the Manager change the FAQ.",
    // new
    "មានតែម្ចាស់ និងអ្នកគ្រប់គ្រងទេដែលកែសំណួរញឹកញាប់។",
  ],
  e_faq_stale: [
    "This question changed meanwhile. The list was read again.",
    // new
    "សំណួរនេះបានប្ដូររួចហើយ។ បញ្ជីត្រូវបានអានម្ដងទៀត។",
  ],
  // Telegram bots step 3a (DL-171): Bookings › Visit requests, words from the mock-up rounds 9,
  // 10 and 13 (i18n11.js, i18n13.js, i18n25.js; keys vr_*, ch_*).
  vr_sub: [
    "New customers who asked to see a Unit. Oldest first: first come, first served.",
    "អតិថិជនថ្មីដែលសុំមកមើលបន្ទប់។ ចាស់មុន៖ មកមុន បានមុន។",
  ],
  vr_how: [
    "Customers send a request from the Telegram bot. They choose how we contact them: Telegram, email, phone call or SMS, or WhatsApp. A new request from the same phone joins the open one and keeps its place.",
    "អតិថិជនផ្ញើសំណើពី Telegram bot។ ពួកគេជ្រើសរបៀបទាក់ទង៖ Telegram អ៊ីមែល ទូរស័ព្ទ ឬ SMS ឬ WhatsApp។ សំណើថ្មីពីលេខទូរស័ព្ទដដែល ភ្ជាប់ទៅសំណើដែលកំពុងបើក ហើយរក្សាលំដាប់ដដែល។",
  ],
  vr_title: ["Visit requests", "សំណើមកមើលបន្ទប់"],
  vr_n: ["{0} requests", "សំណើ {0}"],
  vr_none: ["No visit requests here.", "គ្មានសំណើមកមើលបន្ទប់នៅទីនេះទេ។"],
  vr_col_req: ["Request", "សំណើ"],
  vr_col_who: ["Customer", "អតិថិជន"],
  vr_col_ch: ["Contact by", "ទាក់ទងតាម"],
  vr_col_wants: ["Wants", "ចង់បាន"],
  vr_col_pref: ["Prefers", "ចូលចិត្ត"],
  vr_col_note: ["Note from the person", "កំណត់សម្គាល់ពីអ្នកសុំ"],
  vr_col_status: ["Status", "ស្ថានភាព"],
  vr_movein: ["move in {0}", "ចូលនៅ {0}"],
  vr_later: ["Later", "ពេលក្រោយ"],
  vr_no_day: [
    "No day yet",
    // new
    "មិនទាន់កំណត់ថ្ងៃ",
  ],
  vr_joins: [
    "joins {0}",
    // new
    "ភ្ជាប់ទៅ {0}",
  ],
  ch_TELEGRAM: ["Telegram", "Telegram"],
  ch_EMAIL: ["Email", "អ៊ីមែល"],
  ch_PHONE: ["Phone call or SMS", "ទូរស័ព្ទ ឬ SMS"],
  ch_WHATSAPP: ["WhatsApp", "WhatsApp"],
  part_MORNING: ["Morning", "ព្រឹក"],
  part_AFTERNOON: ["Afternoon", "រសៀល"],
  vst_NEW: ["New", "ថ្មី"],
  vst_JOINED: ["Joined", "បានភ្ជាប់"],
  // Step 3b (DL-172): working a request, words from the CRM mock-up (owner 28 Oct 2026). All
  // the Khmer below is new and needs the native check.
  vst_CONTACTED: ["Contacted", "បានទាក់ទង"],
  vst_VISIT_BOOKED: ["Visit booked", "បានកក់ការមកមើល"],
  vst_VISITED: ["Visited", "បានមកមើល"],
  vst_NO_SHOW: ["No-show", "មិនបានមក"],
  vst_CLOSED: ["Not interested", "មិនចាប់អារម្មណ៍"],
  vst_CANCELLED: ["Cancelled", "បានបោះបង់"],
  vst_SPAM: ["Spam", "សារឥតបានការ"],
  vst_LATE: ["Late", "យឺត"],
  vr_c_waiting: ["Waiting now", "កំពុងរង់ចាំ"],
  vr_c_waiting_s: ["New, nobody took it yet", "ថ្មី មិនទាន់មាននរណាយក"],
  vr_c_late: ["Late", "យឺត"],
  vr_c_late_s: ["Over 2 working hours", "លើស 2 ម៉ោងធ្វើការ"],
  vr_c_booked: ["Visits booked", "ការមកមើលដែលបានកក់"],
  vr_c_booked_s: ["Waiting for the visit", "កំពុងរង់ចាំការមកមើល"],
  vr_c_mine: ["Mine", "របស់ខ្ញុំ"],
  vr_c_mine_s: ["Open requests you have", "សំណើបើកដែលអ្នកកាន់"],
  vr_showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  vr_show_all: ["Show all", "បង្ហាញទាំងអស់"],
  vr_col_wait: ["Waited", "រង់ចាំ"],
  vr_col_staff: ["Staff", "បុគ្គលិក"],
  vr_wait_hm: ["{0} h {1} min", "{0} ម៉ោង {1} នាទី"],
  vr_answered: ["answered", "បានឆ្លើយ"],
  vr_nobody: ["Nobody yet", "មិនទាន់មាន"],
  vr_open: ["Open {0}", "បើក {0}"],
  sbh_title: ["Send by hand today", "ផ្ញើដោយដៃថ្ងៃនេះ"],
  sbh_sub: [
    "These customers do not use Telegram. Send the words on their channel, then tap Mark sent.",
    "អតិថិជនទាំងនេះមិនប្រើ Telegram ទេ។ សូមផ្ញើពាក្យទាំងនេះតាមមធ្យោបាយរបស់ពួកគេ រួចចុច សម្គាល់ថាបានផ្ញើ។",
  ],
  what_CONFIRMATION: ["Visit confirmation", "ការបញ្ជាក់ការមកមើល"],
  what_REMINDER: ["Reminder: visit tomorrow", "ការរំលឹក៖ មកមើលថ្ងៃស្អែក"],
  sbh_copy: ["Copy text", "ចម្លងអត្ថបទ"],
  sbh_copied: ["Copied", "បានចម្លង"],
  sbh_sent: ["Mark sent", "សម្គាល់ថាបានផ្ញើ"],
  msg_conf: [
    "Your visit is booked.\nDate: {0} at {1}\nAddress: {2}\nStaff: {3}\nTo change the time, reply to this message.",
    "ការមកមើលរបស់អ្នកត្រូវបានកក់។\nថ្ងៃ៖ {0} ម៉ោង {1}\nអាសយដ្ឋាន៖ {2}\nបុគ្គលិក៖ {3}\nបើចង់ប្ដូរម៉ោង សូមឆ្លើយតបសារនេះ។",
  ],
  msg_rem: [
    "Reminder: your visit to CHETANA Residence is tomorrow, {0} at {1}. See you soon.",
    "រំលឹក៖ ការមកមើល CHETANA Residence របស់អ្នកគឺនៅថ្ងៃស្អែក {0} ម៉ោង {1}។ ជួបគ្នាឆាប់ៗ។",
  ],
  wd_1: ["Monday", "ថ្ងៃច័ន្ទ"],
  wd_2: ["Tuesday", "ថ្ងៃអង្គារ"],
  wd_3: ["Wednesday", "ថ្ងៃពុធ"],
  wd_4: ["Thursday", "ថ្ងៃព្រហស្បតិ៍"],
  wd_5: ["Friday", "ថ្ងៃសុក្រ"],
  wd_6: ["Saturday", "ថ្ងៃសៅរ៍"],
  wd_7: ["Sunday", "ថ្ងៃអាទិត្យ"],
  d_phone: ["Phone", "ទូរស័ព្ទ"],
  d_arrived: ["Arrived", "មកដល់"],
  d_visit: ["Visit", "ការមកមើល"],
  d_shown_by: ["{0}, shown by {1}", "{0} បង្ហាញដោយ {1}"],
  d_calls: ["Call tries", "ការហៅ"],
  d_reason: ["Why it closed", "មូលហេតុបិទ"],
  d_take: ["Take", "យក"],
  d_has: [
    "{0} has this request. Only {0} or a Manager can work on it.",
    "{0} កាន់សំណើនេះ។ មានតែ {0} ឬអ្នកគ្រប់គ្រងទេ ដែលអាចធ្វើការលើវា។",
  ],
  d_call: ["Record a call", "កត់ត្រាការហៅ"],
  d_answered: ["Answered", "បានឆ្លើយ"],
  d_no_answer: ["No answer", "មិនឆ្លើយ"],
  d_no_days: ["No-answer days: {0} of 3", "ថ្ងៃមិនឆ្លើយ៖ {0} ក្នុង 3"],
  d_no_reach: ["Close: Could not reach", "បិទ៖ ទាក់ទងមិនបាន"],
  d_book: ["Book a visit", "កក់ការមកមើល"],
  d_move: ["Move the visit", "ប្ដូរការមកមើល"],
  d_day: ["Day", "ថ្ងៃ"],
  d_time: ["Time", "ម៉ោង"],
  d_shows: ["Shows the Unit", "អ្នកបង្ហាញបន្ទប់"],
  d_book_btn: ["Book visit", "កក់ការមកមើល"],
  d_move_btn: ["Move visit", "ប្ដូរការមកមើល"],
  d_book_help: [
    "Monday to Saturday, 07:00 to 17:00.",
    "ថ្ងៃច័ន្ទ ដល់ថ្ងៃសៅរ៍ ម៉ោង 07:00 ដល់ 17:00។",
  ],
  d_bot_sends: [
    "The customer gets the confirmation on Telegram, and a reminder at 08:00 the day before.",
    "អតិថិជននឹងទទួលការបញ្ជាក់តាម Telegram និងការរំលឹកនៅម៉ោង 08:00 មួយថ្ងៃមុន។",
  ],
  d_hand_sends: [
    "The confirmation and the reminder go to Send by hand today.",
    "ការបញ្ជាក់ និងការរំលឹក នឹងទៅ ផ្ញើដោយដៃថ្ងៃនេះ។",
  ],
  e_day: [
    "Choose a day from today, not a Sunday.",
    "សូមជ្រើសថ្ងៃចាប់ពីថ្ងៃនេះ មិនមែនថ្ងៃអាទិត្យ។",
  ],
  d_visited: ["Visited", "បានមកមើល"],
  d_no_show: ["No-show", "មិនបានមក"],
  d_close: ["Not interested", "មិនចាប់អារម្មណ៍"],
  d_reason_l: ["Reason", "មូលហេតុ"],
  d_close_btn: ["Close request", "បិទសំណើ"],
  d_cancelled: ["Customer cancelled", "អតិថិជនបានបោះបង់"],
  reason_PRICE: ["Price too high", "តម្លៃខ្ពស់ពេក"],
  reason_TYPE_NOT_FREE: ["Unit Type not free", "ប្រភេទបន្ទប់មិនទំនេរ"],
  reason_LOCATION: ["Location", "ទីតាំង"],
  reason_FOUND_OTHER: ["Found another place", "រកបានកន្លែងផ្សេង"],
  reason_MOVE_IN_FAR: ["Move-in date too far", "ថ្ងៃចូលនៅឆ្ងាយពេក"],
  reason_NO_REACH: ["Could not reach", "ទាក់ទងមិនបាន"],
  reason_OTHER: ["Other (with a note)", "ផ្សេងទៀត (មានកំណត់សម្គាល់)"],
  reason_CANCELLED: ["Customer cancelled", "អតិថិជនបានបោះបង់"],
  d_note_l: ["Note", "កំណត់សម្គាល់"],
  e_note: ["Write a note.", "សូមសរសេរកំណត់សម្គាល់។"],
  d_reopen: ["Reopen", "បើកឡើងវិញ"],
  d_reopen_l: ["Why reopen", "ហេតុអ្វីបើកឡើងវិញ"],
  d_manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  d_give: ["Give to", "ផ្ដល់ទៅ"],
  d_spam: ["Mark Spam", "សម្គាល់ថាជាសារឥតបានការ"],
  d_spam_l: ["Why Spam", "ហេតុអ្វីជាសារឥតបានការ"],
  d_hist: ["History (kept, never deleted)", "ប្រវត្តិ (រក្សាទុក មិនលុបទេ)"],
  h_TAKEN: ["{0} took it", "{0} បានយក"],
  h_GIVEN: ["Given to {0}", "បានផ្ដល់ទៅ {0}"],
  h_CALL_yes: ["Call: answered", "ការហៅ៖ បានឆ្លើយ"],
  h_CALL_no: ["Call: no answer", "ការហៅ៖ មិនឆ្លើយ"],
  h_VISIT_BOOKED: ["Visit booked: {0}", "បានកក់ការមកមើល៖ {0}"],
  h_VISITED: ["Visited", "បានមកមើល"],
  h_NO_SHOW: ["No-show", "មិនបានមក"],
  h_CLOSED: ["Closed: {0}", "បានបិទ៖ {0}"],
  h_REOPENED: ["Reopened", "បានបើកឡើងវិញ"],
  h_SPAM: ["Marked Spam", "បានសម្គាល់ថាជាសារឥតបានការ"],
  h_SENT_BY_HAND: ["Sent by hand: {0}", "បានផ្ញើដោយដៃ៖ {0}"],
  h_REMINDER_DUE: ["Reminder due", "ដល់ពេលរំលឹក"],
  h_bot: ["The bot sent the message.", "បូតបានផ្ញើសារ។"],
  h_by: ["by {0}", "ដោយ {0}"],
  e_vr_stale: [
    "This request changed meanwhile. It was read again.",
    "សំណើនេះបានប្ដូររួចហើយ។ វាត្រូវបានអានម្ដងទៀត។",
  ],
  vr_saved: ["Saved.", "បានរក្សាទុក។"],
  close_dlg: ["Close", "បិទ"],
  // Step 3c (DL-173): Make Reservation, Block, the 12-month removal and this month. New Khmer.
  vst_RESERVED: ["Became Reservation", "បានក្លាយជាការកក់"],
  h_RESERVED: ["Became a Reservation", "បានក្លាយជាការកក់"],
  d_make_res: ["Make Reservation", "បង្កើតការកក់"],
  d_res_open: ["Open the Reservation", "បើកការកក់"],
  d_block: ["Block Telegram account", "បិទគណនី Telegram"],
  d_block_l: ["Why block", "ហេតុអ្វីបិទ"],
  d_unblock: ["Unblock Telegram account", "បើកគណនី Telegram វិញ"],
  d_blocked: [
    "This Telegram account is blocked. It cannot send requests or messages.",
    "គណនី Telegram នេះត្រូវបានបិទ។ វាមិនអាចផ្ញើសំណើ ឬសារបានទេ។",
  ],
  d_removed: [
    "The name, phone and email were removed after 12 months with no activity.",
    "ឈ្មោះ ទូរស័ព្ទ និងអ៊ីមែល ត្រូវបានលុប ក្រោយ 12 ខែគ្មានសកម្មភាព។",
  ],
  m_title: ["This month", "ខែនេះ"],
  m_new: ["New requests", "សំណើថ្មី"],
  m_joined: ["Asked again", "សុំម្ដងទៀត"],
  m_VISIT_BOOKED: ["Visits booked", "ការមកមើលដែលបានកក់"],
  m_VISITED: ["Visited", "បានមកមើល"],
  m_NO_SHOW: ["No-show", "មិនបានមក"],
  m_RESERVED: ["Became Reservation", "បានក្លាយជាការកក់"],
  m_CLOSED: ["Closed", "បានបិទ"],
  m_SPAM: ["Spam", "សារឥតបានការ"],
  m_reasons: ["Why requests closed", "ហេតុអ្វីសំណើត្រូវបានបិទ"],
  m_sources: ["Where requests came from", "សំណើមកពីណា"],
  m_none: ["None yet.", "មិនទាន់មាន។"],
  m_count: ["Count", "ចំនួន"],
  src_TELEGRAM: ["Telegram bot", "បូត Telegram"],
  // Invoices on Telegram (DL-211, owner 8 Nov 2026). All Khmer here is new and needs the
  // native check.
  inv_h: ["Invoices on Telegram", "វិក្កយបត្រតាមតេឡេក្រាម"],
  inv_sub: [
    "Each issued Invoice goes to the tenants linked to its Lease. A reminder goes {0} days before the due date while it is not fully paid. Invoices of the last {1} days.",
    "វិក្កយបត្រដែលបានចេញនីមួយៗ ផ្ញើទៅអ្នកជួលដែលភ្ជាប់នឹងកិច្ចសន្យា។ ការរំលឹកផ្ញើ {0} ថ្ងៃមុនកាលកំណត់បង់ ប្រសិនបើមិនទាន់បង់គ្រប់។ វិក្កយបត្រ {1} ថ្ងៃចុងក្រោយ។",
  ],
  inv_paper_t: [
    "Invoices that did not reach anyone on Telegram: {0}. Give these tenants a paper copy.",
    "វិក្កយបត្រ {0} មិនបានទៅដល់នរណាម្នាក់តាមតេឡេក្រាមទេ។ សូមផ្តល់ច្បាប់ចម្លងក្រដាសដល់អ្នកជួលទាំងនេះ។",
  ],
  inv_none: [
    "No Invoices were issued in this time.",
    "មិនមានវិក្កយបត្រចេញក្នុងរយៈពេលនេះទេ។",
  ],
  c_invoice: ["Invoice", "វិក្កយបត្រ"],
  c_due: ["Due date", "កាលកំណត់បង់"],
  c_to_pay: ["To pay", "ត្រូវបង់"],
  c_telegram: ["Telegram", "តេឡេក្រាម"],
  c_reminder: ["Reminder", "ការរំលឹក"],
  inv_sent: ["Sent to {0}", "បានផ្ញើទៅ {0}"],
  inv_waiting: ["Waiting to send", "កំពុងរង់ចាំផ្ញើ"],
  inv_failed: ["Not delivered", "មិនបានទៅដល់"],
  inv_paper: ["Give a paper copy", "ផ្តល់ច្បាប់ចម្លងក្រដាស"],
  inv_no_reminder: ["Not yet", "មិនទាន់"],
} as const satisfies Record<string, readonly [string, string]>;

export type TelegramTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function tt(
  language: Language,
  key: TelegramTextKey,
  ...values: (string | number)[]
): string {
  const words: string = TEXT[key][language === "km" ? 1 : 0];
  return words.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

/** A server code with its own words; an unknown code shows as it is. */
export function hasText(key: string): key is TelegramTextKey {
  return key in TEXT;
}
