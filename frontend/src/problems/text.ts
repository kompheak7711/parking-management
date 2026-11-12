// V1.1 part 7 (DL-124): the words of Building › Problem reports, in English and Khmer, from the
// mock-up rounds 29 and 32 (i18n34.js, i18n37.js). Khmer marked "new" is not in the mock-up and
// needs the native check.

import type { Language } from "../signInText";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: ["This could not be read just now.", "មិនអាចអានបានទេឥឡូវនេះ។"],
  retry: ["Try again", "សាកម្តងទៀត"],
  back: ["Back to Problem reports", "ត្រឡប់ទៅរបាយការណ៍បញ្ហា"],
  no_property: ["Choose a Property first.", "សូមជ្រើសអចលនទ្រព្យជាមុន។"],
  not_found: [
    "This Problem report was not found.",
    // new
    "រកមិនឃើញរបាយការណ៍បញ្ហានេះទេ។",
  ],
  cancel: ["Cancel", "បោះបង់"],
  required: ["required", "ចាំបាច់"],
  yes: ["Yes", "បាទ/ចាស"],
  no: ["No", "ទេ"],
  // List
  sub: [
    "One list for every problem in a Unit or in the building. Oldest first.",
    "បញ្ជីតែមួយសម្រាប់បញ្ហាទាំងអស់ក្នុងបន្ទប់ ឬក្នុងអគារ។ ចាស់មុន។",
  ],
  add: ["New Problem report", "របាយការណ៍បញ្ហាថ្មី"],
  tab_open: ["Open", "កំពុងបើក"],
  tab_urgent: ["Urgent", "បន្ទាន់"],
  tab_late: ["Late", "យឺត"],
  tab_done: ["Done", "រួចរាល់"],
  tabs: ["Which reports", "របាយការណ៍ណាខ្លះ"],
  f_kind: ["Kind", "ប្រភេទរបាយការណ៍"],
  f_type: ["Type", "ប្រភេទបញ្ហា"],
  f_all: ["All", "ទាំងអស់"],
  f_clear: ["Clear filters", "សម្អាតតម្រង"],
  f_none: [
    "No reports match these filters.",
    "គ្មានរបាយការណ៍ត្រូវនឹងតម្រងទាំងនេះទេ។",
  ],
  none: [
    "No Problem reports here.",
    // new
    "គ្មានរបាយការណ៍បញ្ហានៅទីនេះទេ។",
  ],
  c_no: ["Number", "លេខ"],
  c_kind: ["Kind", "ប្រភេទរបាយការណ៍"],
  c_type: ["Type", "ប្រភេទបញ្ហា"],
  c_where: ["Unit or place", "បន្ទប់ ឬកន្លែង"],
  c_src: ["Source", "ប្រភព"],
  c_status: ["Status", "ស្ថានភាព"],
  c_who: ["Person in charge", "អ្នកទទួលខុសត្រូវ"],
  c_age: ["Age", "រយៈពេល"],
  n1: ["1 report", "របាយការណ៍ 1"],
  n: ["{0} reports", "របាយការណ៍ {0}"],
  urgent: ["Urgent", "បន្ទាន់"],
  repeat: ["Repeat", "ម្ដងទៀត"],
  joined_n: ["+{0} joined", "+{0} បានភ្ជាប់"],
  joined_to: ["Joined to {0}", "បានភ្ជាប់ទៅ {0}"],
  follows: ["follows {0}", "តាម {0}"],
  not_planned: ["Not planned yet", "មិនទាន់រៀបចំ"],
  late_u: [
    "Late: the tenant is not contacted yet",
    // new
    "យឺត៖ មិនទាន់ទាក់ទងអ្នកជួល",
  ],
  late_n: [
    "Late: not planned in time",
    // new
    "យឺត៖ មិនបានរៀបចំទាន់ពេល",
  ],
  w_m: ["{0} min", "{0} នាទី"],
  w_hm: ["{0} h {1} min", "{0} ម៉ោង {1} នាទី"],
  w_dh: ["{0} d {1} h", "{0} ថ្ងៃ {1} ម៉ោង"],
  floor: ["floor {0}", "ជាន់ {0}"],
  no_lease: ["no Lease", "គ្មានកិច្ចសន្យា"],
  // Kinds, sources, statuses
  k_UNIT: ["Unit Problem", "បញ្ហាបន្ទប់"],
  k_UNIT_s: ["inside a Unit", "ក្នុងបន្ទប់"],
  k_BUILDING: ["Building problem", "បញ្ហាអគារ"],
  k_BUILDING_s: ["shared places", "កន្លែងរួម"],
  src_PHONE: ["App · phone call", "កម្មវិធី · ទូរស័ព្ទ"],
  src_WALKIN: ["App · walk-in", "កម្មវិធី · មកផ្ទាល់"],
  src_SEEN: ["App · seen by staff", "កម្មវិធី · បុគ្គលិកឃើញ"],
  src_INSPECTION: ["Inspection", "ការត្រួតពិនិត្យ"],
  src_TENANT_BOT: ["Tenant bot", "បូតអ្នកជួល"],
  src_STAFF_BOT: ["Staff bot", "បូតបុគ្គលិក"],
  src_ROOM_CHECK: ["Short-stay room check", "ការពិនិត្យបន្ទប់ស្នាក់នៅខ្លី"],
  st_RECEIVED: ["Received", "បានទទួល"],
  st_PLANNED: ["Visit planned", "បានរៀបចំការមកពិនិត្យ"],
  st_CHECKED: ["Checked", "បានពិនិត្យ"],
  st_WAITING_TENANT: ["Waiting for the tenant", "រង់ចាំអ្នកជួល"],
  st_REPAIR_PLANNED: ["Repair planned", "បានរៀបចំការជួសជុល"],
  st_WAITING_PARTS: ["Waiting for parts", "រង់ចាំគ្រឿងបន្លាស់"],
  st_DONE: ["Done", "រួចរាល់"],
  st_CLOSED: ["Closed", "បានបិទ"],
  st_NOT_ACCEPTED: ["Not accepted", "មិនទទួលយក"],
  st_JOINED: ["Joined", "បានភ្ជាប់"],
  b_AM: ["Morning", "ពេលព្រឹក"],
  b_PM: ["Afternoon", "ពេលរសៀល"],
  b_ANY: ["Any time", "ពេលណាក៏បាន"],
  cause_WEAR: ["Normal wear or old age", "ពុកផុយតាមការប្រើប្រាស់"],
  cause_DAMAGE: ["Damage by the tenant", "ខូចដោយអ្នកជួល"],
  cause_UNSURE: ["Not sure", "មិនប្រាកដ"],
  // New Problem report
  add_t: ["New Problem report", "របាយការណ៍បញ្ហាថ្មី"],
  add_kind: ["What kind", "ប្រភេទ"],
  add_how: ["How did you hear about it?", "អ្នកដឹងតាមរបៀបណា?"],
  how_PHONE: ["Phone call", "ទូរស័ព្ទ"],
  how_WALKIN: ["Walk-in", "មកផ្ទាល់"],
  how_SEEN: ["Seen by staff", "បុគ្គលិកឃើញ"],
  add_unit: ["Unit", "បន្ទប់"],
  add_unit_pick: ["Choose the Unit", "ជ្រើសបន្ទប់"],
  add_place: ["Place in the Unit (if known)", "កន្លែងក្នុងបន្ទប់ (បើដឹង)"],
  add_place_any: ["Not sure", "មិនប្រាកដ"],
  add_where: ["Where in the building", "នៅណាក្នុងអគារ"],
  add_where_pick: ["Choose the place", "ជ្រើសកន្លែង"],
  add_floor: ["Floor (if known)", "ជាន់ (បើដឹង)"],
  add_by: ["Who reported it (if any)", "អ្នករាយការណ៍ (បើមាន)"],
  add_type: ["Type", "ប្រភេទបញ្ហា"],
  always: ["Always urgent", "បន្ទាន់ជានិច្ច"],
  safety_n: [
    "Safety is always urgent. Make people safe first, then call the Manager.",
    // new
    "សុវត្ថិភាពបន្ទាន់ជានិច្ច។ ធ្វើឱ្យមនុស្សមានសុវត្ថិភាពជាមុន រួចហៅអ្នកគ្រប់គ្រង។",
  ],
  add_text: ["What is wrong", "មានបញ្ហាអ្វី"],
  add_text_ph: [
    "For example: water leaks under the kitchen sink",
    "ឧទាហរណ៍៖ ទឹកលេចក្រោមស៊ីងផ្ទះបាយ",
  ],
  add_urgent: ["Is it urgent?", "បន្ទាន់ឬទេ?"],
  add_enter: [
    "May staff enter when the tenant is out?",
    "អាចចូលពេលអ្នកជួលមិននៅទេ?",
  ],
  add_best: ["Best time to come", "ពេលល្អបំផុតដើម្បីមក"],
  same_t: ["Open reports here ({0})", "របាយការណ៍បើកនៅទីនេះ ({0})"],
  same_b: ["Same problem", "បញ្ហាដូចគ្នា"],
  same_s: [
    "Same problem saves this report with its own number, joined to that report.",
    // new
    "បញ្ហាដូចគ្នា រក្សាទុករបាយការណ៍នេះជាមួយលេខរបស់វា ហើយភ្ជាប់ទៅរបាយការណ៍នោះ។",
  ],
  add_save: ["Save report", "រក្សាទុករបាយការណ៍"],
  e_unit: ["Choose the Unit.", "ជ្រើសបន្ទប់។"],
  e_where: ["Choose the place.", "ជ្រើសកន្លែង។"],
  e_type: ["Choose the type.", "ជ្រើសប្រភេទបញ្ហា។"],
  e_text: ["Please write this.", "សូមសរសេរ។"],
  added: ["{0} added. Status: Received.", "បានបញ្ចូល {0}។ ស្ថានភាព៖ បានទទួល។"],
  added_same: [
    "Saved as {0}, joined to {1}.",
    "បានរក្សាទុកជា {0} ភ្ជាប់ទៅ {1}។",
  ],
  // One report
  received_ago: ["received {0} ago", "បានទទួល {0} មុន"],
  added_by: ["added by {0}", "បញ្ចូលដោយ {0}"],
  det: ["Details", "ព័ត៌មានលម្អិត"],
  next: ["Next step", "ជំហានបន្ទាប់"],
  hist: ["History", "ប្រវត្តិ"],
  d_where: ["Unit or place", "បន្ទប់ ឬកន្លែង"],
  d_tenant: ["Tenant", "អ្នកជួល"],
  d_text: ["What is wrong", "មានបញ្ហាអ្វី"],
  d_by: ["Reported by", "រាយការណ៍ដោយ"],
  d_enter: ["Staff may enter", "បុគ្គលិកអាចចូល"],
  d_best: ["Best time", "ពេលល្អបំផុត"],
  d_tech: ["Technician and time", "ជាងបច្ចេកទេស និងម៉ោង"],
  d_cause: ["Cause", "មូលហេតុ"],
  d_pays: ["Who pays", "អ្នកចេញថ្លៃ"],
  pays_none: [
    "Not decided yet (after the check)",
    "មិនទាន់សម្រេច (ក្រោយការពិនិត្យ)",
  ],
  pays_OWNER: ["Owner pays", "ម្ចាស់ចេញថ្លៃ"],
  pays_TENANT: ["Tenant pays", "អ្នកជួលចេញថ្លៃ"],
  pays_t: ["Tenant pays {0} ({1})", "អ្នកជួលចេញ {0} ({1})"],
  when: ["{0}, {1} at {2}", "{0}, {1} ម៉ោង {2}"],
  fixed_check: ["already fixed (urgent)", "បានជួសជុលរួច (បន្ទាន់)"],
  repeat_t: [
    "Repeat problem: {0} times in {1} days",
    "បញ្ហាម្ដងទៀត៖ {0} ដងក្នុង {1} ថ្ងៃ",
  ],
  late_t: ["Late: {0}", "យឺត៖ {0}"],
  tell_n: [
    "Telegram messages to the tenant come later. Tell the tenant by phone for now.",
    // new
    "សារតេឡេក្រាមទៅអ្នកជួលនឹងមកនៅពេលក្រោយ។ សម្រាប់ពេលនេះ សូមប្រាប់អ្នកជួលតាមទូរស័ព្ទ។",
  ],
  lock_n: [
    "Only a Manager or the Owner plans repairs and decides who pays.",
    // new
    "មានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ ទើបរៀបចំការជួសជុល និងសម្រេចអ្នកចេញថ្លៃ។",
  ],
  // Next step words
  n_RECEIVED_u: [
    "Urgent: contact the tenant within {0} h.",
    "បន្ទាន់៖ ទាក់ទងអ្នកជួលក្នុង {0} ម៉ោង។",
  ],
  n_RECEIVED: [
    "Plan the check visit, or say it is not a repair.",
    // new
    "រៀបចំការមកពិនិត្យ ឬប្រាប់ថាមិនមែនការជួសជុល។",
  ],
  n_BP: ["Building problem: choose one", "បញ្ហាអគារ៖ ជ្រើសរើសមួយ"],
  n_BP_s: [
    "A repair job keeps this number and gets a technician and a time.",
    "ការងារជួសជុលរក្សាលេខនេះ ហើយទទួលបានជាង និងម៉ោង។",
  ],
  n_PLANNED: [
    "{0} comes {1}. After the visit, write the check report.",
    // new
    "{0} នឹងមក {1}។ ក្រោយការមក សូមសរសេររបាយការណ៍ពិនិត្យ។",
  ],
  n_CHECKED: ["Decide who pays.", "សម្រេចអ្នកចេញថ្លៃ។"],
  n_WAITING_TENANT: [
    "Ask the tenant. When the tenant agrees, the Damage Invoice draft is made at once.",
    // new
    "សួរអ្នកជួល។ ពេលអ្នកជួលយល់ព្រម សេចក្ដីព្រាងវិក្កយបត្រខូចខាតត្រូវបានធ្វើភ្លាម។",
  ],
  n_REPAIR_PLANNED: [
    "Do the repair. Mark it done, or say it waits for parts.",
    // new
    "ធ្វើការជួសជុល។ សម្គាល់ថារួចរាល់ ឬប្រាប់ថារង់ចាំគ្រឿងបន្លាស់។",
  ],
  n_WAITING_PARTS: [
    "Work is paused until the parts arrive.",
    // new
    "ការងារផ្អាករហូតដល់គ្រឿងបន្លាស់មកដល់។",
  ],
  n_DONE: [
    "Waiting for the tenant: Fixed or Not fixed. If there is no answer, it closes by itself on {0}.",
    // new
    "រង់ចាំអ្នកជួល៖ ជួសជុលរួច ឬមិនទាន់រួច។ បើគ្មានការឆ្លើយ វាបិទដោយខ្លួនឯងនៅ {0}។",
  ],
  n_DONE_close: [
    "The repair is done. Close the report.",
    // new
    "ការជួសជុលរួចរាល់។ សូមបិទរបាយការណ៍។",
  ],
  n_closed: ["Nothing more to do.", "គ្មានអ្វីត្រូវធ្វើទៀតទេ។"],
  n_JOINED: [
    "This report follows {0}. Its updates come from that report.",
    // new
    "របាយការណ៍នេះតាម {0}។ ព័ត៌មានថ្មីមកពីរបាយការណ៍នោះ។",
  ],
  // Step buttons and dialogs
  s_CONTACTED: ["Contacted", "បានទាក់ទង"],
  s_PLAN: ["Plan the check visit", "រៀបចំការមកពិនិត្យ"],
  s_REPLAN: [
    "Change the visit",
    // new
    "ប្ដូរការមកពិនិត្យ",
  ],
  s_NOT_A_REPAIR: ["Not a repair", "មិនមែនការជួសជុល"],
  s_MAKE_JOB: ["Make a repair job", "បង្កើតការងារជួសជុល"],
  s_CLEANING: ["Give to cleaning", "ប្រគល់ឱ្យផ្នែកសម្អាត"],
  s_CLOSE_NOTE: ["Close with a note", "បិទដោយមានកំណត់ចំណាំ"],
  s_CHECKED: [
    "Write the check report",
    // new
    "សរសេររបាយការណ៍ពិនិត្យ",
  ],
  s_DECIDE: ["Decide who pays", "សម្រេចអ្នកចេញថ្លៃ"],
  s_ANSWER: [
    "Tenant's answer",
    // new
    "ចម្លើយរបស់អ្នកជួល",
  ],
  s_PARTS: ["Waiting for parts", "រង់ចាំគ្រឿងបន្លាស់"],
  s_PARTS_ARRIVED: ["Parts arrived", "គ្រឿងបន្លាស់មកដល់"],
  s_DONE: [
    "Repair done",
    // new
    "ជួសជុលរួចរាល់",
  ],
  s_TENANT_FIXED: ["Tenant says Fixed", "អ្នកជួលថា ជួសជុលរួច"],
  s_TENANT_NOT_FIXED: ["Tenant says Not fixed", "អ្នកជួលថា មិនទាន់រួច"],
  s_CLOSE: ["Close", "បិទ"],
  s_JOIN: ["Join to a report", "ភ្ជាប់ទៅរបាយការណ៍"],
  s_UNJOIN: ["Undo join", "ដកការភ្ជាប់"],
  t_step: ["{0} · {1}", "{0} · {1}"],
  con_how: ["How", "របៀប"],
  con_PHONE: ["Phone call", "ទូរស័ព្ទ"],
  con_VISIT: ["Went to the Unit", "ទៅដល់បន្ទប់"],
  note_opt: ["Note (if any)", "កំណត់ចំណាំ (បើមាន)"],
  note: ["Note", "កំណត់ចំណាំ"],
  note_h: [
    "Kept in the history. It cannot be deleted.",
    "រក្សាទុកក្នុងប្រវត្តិ។ មិនអាចលុបបានទេ។",
  ],
  why_tenant: ["Reason (the tenant sees it)", "មូលហេតុ (អ្នកជួលឃើញ)"],
  tech: ["Technician", "ជាងបច្ចេកទេស"],
  tech_h: [
    "Type the name for now. The Employees list comes later.",
    // new
    "វាយឈ្មោះសម្រាប់ពេលនេះ។ បញ្ជីបុគ្គលិកនឹងមកពេលក្រោយ។",
  ],
  day: ["Day", "ថ្ងៃ"],
  time: ["Time", "ម៉ោង"],
  time_pick: ["Choose the time", "ជ្រើសម៉ោង"],
  best_hint: [
    "Tenant's best time: {0}. A check takes about 30 minutes.",
    "ពេលល្អរបស់អ្នកជួល៖ {0}។ ការពិនិត្យចំណាយពេលប្រហែល ៣០ នាទី។",
  ],
  cleaner: ["Cleaner", "អ្នកសម្អាត"],
  clean_n: [
    "The cleaner handles it. The report is then Done.",
    // new
    "អ្នកសម្អាតដោះស្រាយ។ បន្ទាប់មករបាយការណ៍រួចរាល់។",
  ],
  cause: ["Cause", "មូលហេតុ"],
  tech_note: ["Technician's note", "កំណត់ចំណាំរបស់ជាង"],
  fixed_q: [
    "Already fixed at the check (urgent work)",
    // new
    "បានជួសជុលរួចពេលពិនិត្យ (ការងារបន្ទាន់)",
  ],
  unsure_n: [
    "Not sure: look again or go to see, then decide.",
    "មិនប្រាកដ៖ មើលម្ដងទៀត ឬទៅមើលផ្ទាល់ រួចសម្រេច។",
  ],
  pays: ["Who pays", "អ្នកចេញថ្លៃ"],
  amount: ["Amount the tenant pays", "ចំនួនដែលអ្នកជួលបង់"],
  amount_h: [
    "US dollars, for example 25.00. The Damage Invoice draft uses this amount.",
    // new
    "ដុល្លារអាមេរិក ឧទាហរណ៍ 25.00។ សេចក្ដីព្រាងវិក្កយបត្រខូចខាតប្រើចំនួននេះ។",
  ],
  tenant_no_lease: [
    "This Unit has no signed Lease, so no tenant can pay.",
    // new
    "បន្ទប់នេះគ្មានកិច្ចសន្យាដែលបានចុះហត្ថលេខា ដូច្នេះគ្មានអ្នកជួលអាចបង់បានទេ។",
  ],
  ans_t: ["Tenant's answer · {0}", "ចម្លើយរបស់អ្នកជួល · {0}"],
  ans_q: [
    "What did the tenant say to {0}?",
    // new
    "អ្នកជួលនិយាយយ៉ាងណាចំពោះ {0}?",
  ],
  ans_AGREED: ["Agreed", "យល់ព្រម"],
  ans_REFUSED: ["Refused", "បដិសេធ"],
  ans_how: [
    "How the tenant answered",
    // new
    "អ្នកជួលឆ្លើយតាមរបៀបណា",
  ],
  how_SIGNED: ["Signed a paper", "ចុះហត្ថលេខាលើក្រដាស"],
  how_TELEGRAM: ["Telegram", "តេឡេក្រាម"],
  how_IN_PERSON: ["In person", "ផ្ទាល់"],
  ans_on: [
    "Day the tenant answered",
    // new
    "ថ្ងៃដែលអ្នកជួលឆ្លើយ",
  ],
  ans_said: [
    "What the tenant said",
    // new
    "អ្វីដែលអ្នកជួលបាននិយាយ",
  ],
  ans_next: [
    "What happens next",
    // new
    "អ្វីកើតឡើងបន្ទាប់",
  ],
  after_OWNER_PAYS: [
    "The Owner pays and the repair goes ahead",
    // new
    "ម្ចាស់ចេញថ្លៃ ហើយការជួសជុលបន្ត",
  ],
  after_MOVE_OUT: [
    "Leave it for the move-out inspection (the report closes)",
    // new
    "ទុកសម្រាប់ការត្រួតពិនិត្យពេលចាកចេញ (របាយការណ៍បិទ)",
  ],
  ans_agree_n: [
    "Saving makes the Damage Invoice draft for {0} at once.",
    // new
    "ការរក្សាទុកធ្វើសេចក្ដីព្រាងវិក្កយបត្រខូចខាតសម្រាប់ {0} ភ្លាម។",
  ],
  join_main: ["Main report", "របាយការណ៍មេ"],
  join_pick: ["Choose the main report", "ជ្រើសរបាយការណ៍មេ"],
  join_none: [
    "There is no other open report of the same kind here.",
    // new
    "គ្មានរបាយការណ៍បើកផ្សេងទៀតដែលមានប្រភេទដូចគ្នានៅទីនេះទេ។",
  ],
  join_why: ["Reason", "មូលហេតុ"],
  save: ["Save", "រក្សាទុក"],
  e_note: ["Please write this.", "សូមសរសេរ។"],
  e_tech: ["Type the technician's name.", "វាយឈ្មោះជាង។"],
  e_cleaner: ["Type the cleaner's name.", "វាយឈ្មោះអ្នកសម្អាត។"],
  e_day: [
    "Choose a day from today, at most 60 days ahead.",
    // new
    "ជ្រើសថ្ងៃចាប់ពីថ្ងៃនេះ យ៉ាងច្រើន ៦០ ថ្ងៃខាងមុខ។",
  ],
  e_time: ["Pick a time later than now.", "ជ្រើសម៉ោងក្រោយពេលនេះ។"],
  e_cause: ["Choose the cause.", "ជ្រើសមូលហេតុ។"],
  e_pays: ["Choose who pays.", "ជ្រើសអ្នកចេញថ្លៃ។"],
  e_amount: ["Type the amount.", "វាយចំនួនទឹកប្រាក់។"],
  e_pick: ["Choose one.", "ជ្រើសរើសមួយ។"],
  saved: ["{0}: saved.", "{0}៖ បានរក្សាទុក។"],
  agreed_done: [
    "{0}: the tenant agreed. Damage Invoice draft {1} is made.",
    // new
    "{0}៖ អ្នកជួលបានយល់ព្រម។ បានធ្វើសេចក្ដីព្រាងវិក្កយបត្រខូចខាត {1}។",
  ],
  // Who pays and Damage box
  dmg_h: ["Damage Invoice", "វិក្កយបត្រខូចខាត"],
  dmg_amt: [
    "Damage Invoice amount (set by the Manager)",
    // new
    "ចំនួនវិក្កយបត្រខូចខាត (កំណត់ដោយអ្នកគ្រប់គ្រង)",
  ],
  dmg_wait: [
    "The Damage Invoice draft is made when the tenant agrees.",
    // new
    "សេចក្ដីព្រាងវិក្កយបត្រខូចខាតត្រូវបានធ្វើពេលអ្នកជួលយល់ព្រម។",
  ],
  dmg_made: [
    "Made when the tenant agreed.",
    // new
    "បានធ្វើ ពេលអ្នកជួលយល់ព្រម។",
  ],
  dmg_open: [
    "Open Damage Invoice {0}",
    // new
    "បើកវិក្កយបត្រខូចខាត {0}",
  ],
  refused_n: [
    "The tenant refused: {0}",
    // new
    "អ្នកជួលបានបដិសេធ៖ {0}",
  ],
  agreed_n: [
    "The tenant agreed ({0}, {1}).",
    // new
    "អ្នកជួលបានយល់ព្រម ({0}, {1})។",
  ],
  // Joined
  kids_h: ["Joined reports ({0})", "របាយការណ៍ដែលបានភ្ជាប់ ({0})"],
  jn_t: ["Joined to {0}", "បានភ្ជាប់ទៅ {0}"],
  jn_by: ["Joined by {0} · {1}", "ភ្ជាប់ដោយ {0} · {1}"],
  jn_lock: [
    "Only a Manager or the Owner can join reports or undo a join.",
    "មានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ ទើបអាចភ្ជាប់ ឬដកការភ្ជាប់បាន",
  ],
  open_report: [
    "Open {0}",
    // new
    "បើក {0}",
  ],
  // History words
  h_RECEIVED: [
    "Received ({0})",
    // new
    "បានទទួល ({0})",
  ],
  h_CONTACTED: ["Contacted the tenant: {0}", "បានទាក់ទងអ្នកជួល៖ {0}"],
  h_PLANNED: ["Check visit planned: {0}", "បានរៀបចំការមកពិនិត្យ៖ {0}"],
  h_REPLANNED: [
    "Check visit changed: {0}",
    // new
    "បានប្ដូរការមកពិនិត្យ៖ {0}",
  ],
  h_NOT_ACCEPTED: ["Not accepted", "មិនទទួលយក"],
  h_REPAIR_JOB: ["Made a repair job", "បានបង្កើតការងារជួសជុល"],
  h_CLEANING: [
    "Given to cleaning ({0}): Done",
    "បានប្រគល់ឱ្យផ្នែកសម្អាត ({0})៖ រួចរាល់",
  ],
  h_CLOSED_NOTE: ["Closed with a note", "បានបិទដោយកំណត់ចំណាំ"],
  h_CHECKED: ["Check report: {0}", "របាយការណ៍ពិនិត្យ៖ {0}"],
  h_OWNER_PAYS: ["Decided: the Owner pays", "បានសម្រេច៖ ម្ចាស់ចេញថ្លៃ"],
  h_TENANT_PAYS: [
    "Decided: the tenant pays {0}",
    // new
    "បានសម្រេច៖ អ្នកជួលចេញ {0}",
  ],
  h_TENANT_AGREED: [
    "The tenant agreed; Damage Invoice draft made",
    // new
    "អ្នកជួលបានយល់ព្រម ហើយបានធ្វើសេចក្ដីព្រាងវិក្កយបត្រខូចខាត",
  ],
  h_TENANT_REFUSED: [
    "The tenant refused",
    // new
    "អ្នកជួលបានបដិសេធ",
  ],
  h_WAITING_PARTS: ["Waiting for parts", "រង់ចាំគ្រឿងបន្លាស់"],
  h_PARTS_ARRIVED: ["Parts arrived", "គ្រឿងបន្លាស់មកដល់"],
  h_DONE: [
    "Repair done",
    // new
    "ជួសជុលរួចរាល់",
  ],
  h_FIXED: ["The tenant said Fixed: Closed", "អ្នកជួលថា ជួសជុលរួច៖ បានបិទ"],
  h_NOT_FIXED: [
    "The tenant said Not fixed: open again, same number",
    "អ្នកជួលថា មិនទាន់រួច៖ បើកម្ដងទៀត លេខដដែល",
  ],
  h_MANAGER_CLOSED: [
    "Closed by the Manager",
    // new
    "បានបិទដោយអ្នកគ្រប់គ្រង",
  ],
  h_JOINED: ["Joined to {0}", "បានភ្ជាប់ទៅ {0}"],
  h_JOINED_IN: [
    "{0} was joined to this report",
    // new
    "{0} បានភ្ជាប់មករបាយការណ៍នេះ",
  ],
  h_MOVED: [
    "Now follows {0}",
    // new
    "ឥឡូវតាម {0}",
  ],
  h_UNJOINED: [
    "Join undone: its own report again",
    // new
    "បានដកការភ្ជាប់៖ ជារបាយការណ៍ដាច់ដោយឡែកវិញ",
  ],
  h_UNJOINED_OUT: [
    "{0} was taken out of the join",
    // new
    "{0} ត្រូវបានដកចេញពីការភ្ជាប់",
  ],
  // Refusals
  f_right: [
    "You do not have the right to do this. Ask the Owner.",
    // new
    "អ្នកមិនមានសិទ្ធិធ្វើវាទេ។ សូមសួរម្ចាស់។",
  ],
  f_stale: [
    "Someone changed this report meanwhile. It is shown again; check it and try again.",
    // new
    "មាននរណាម្នាក់បានប្ដូររបាយការណ៍នេះ។ វាត្រូវបានបង្ហាញម្ដងទៀត សូមពិនិត្យ ហើយសាកម្ដងទៀត។",
  ],
  f_refused: [
    "The server refused this. Check what you typed and the report's status.",
    // new
    "ម៉ាស៊ីនមេបានបដិសេធ។ ពិនិត្យអ្វីដែលអ្នកបានវាយ និងស្ថានភាពរបាយការណ៍។",
  ],
  f_failed: [
    "This was not saved. Check the connection and try again.",
    "មិនបានរក្សាទុកទេ។ ពិនិត្យការតភ្ជាប់ ហើយសាកម្តងទៀត។",
  ],
  // Repair cost (DL-130, mock-up round 32 A5). Khmer here is new and needs the native check.
  cost_h: ["Repair cost", "ថ្លៃជួសជុល"],
  cost_none: [
    "No cost typed yet. Type parts and outside workers only; our own staff are paid by payroll.",
    "មិនទាន់វាយថ្លៃនៅឡើយ។ វាយតែគ្រឿងបន្លាស់ និងជាងខាងក្រៅ។ បុគ្គលិកយើងទទួលប្រាក់ខែ។",
  ],
  cost_enter: ["Type the cost", "វាយថ្លៃ"],
  cost_again: ["Type the cost again", "វាយថ្លៃម្តងទៀត"],
  cost_by: ["Typed by {0}, {1}", "វាយដោយ {0}, {1}"],
  cost_no_cost: [
    "No cost: the repair cost nothing to pay.",
    "គ្មានថ្លៃ៖ ការជួសជុលមិនចំណាយអ្វីទេ។",
  ],
  cost_total: ["Total", "សរុប"],
  cost_wait: [
    "Waiting for a Manager to check the cost.",
    "កំពុងរង់ចាំអ្នកគ្រប់គ្រងពិនិត្យថ្លៃ។",
  ],
  cost_check: [
    "Checked, make Expense report",
    "បានពិនិត្យ បង្កើតរបាយការណ៍ចំណាយ",
  ],
  cost_checked: [
    "Checked by {0}, {1}. Receipt seen.",
    "បានពិនិត្យដោយ {0}, {1}។ បានឃើញបង្កាន់ដៃ។",
  ],
  cost_er: ["Expense report {0}: {1}", "របាយការណ៍ចំណាយ {0}៖ {1}"],
  cost_refused: [
    "The Expense report was not approved. Staff may type the cost again.",
    "របាយការណ៍ចំណាយមិនត្រូវបានអនុម័ត។ បុគ្គលិកអាចវាយថ្លៃម្តងទៀត។",
  ],
  cost_compare: [
    "For comparison only; it does not change the Damage Invoice draft.",
    "សម្រាប់ប្រៀបធៀបតែប៉ុណ្ណោះ មិនប្តូរសេចក្តីព្រាងវិក្កយបត្រខូចខាតទេ។",
  ],
  kind_PARTS: ["Parts", "គ្រឿងបន្លាស់"],
  kind_OUTSIDE_WORKER: ["Outside worker", "ជាងខាងក្រៅ"],
  cur_USD: ["Dollars", "ដុល្លារ"],
  cur_KHR: ["Riel", "រៀល"],
  cd_t: ["Repair cost of {0}", "ថ្លៃជួសជុល {0}"],
  cd_no_cost: [
    "No cost (fixed by our own staff, nothing bought)",
    "គ្មានថ្លៃ (បុគ្គលិកយើងជួសជុល មិនបានទិញអ្វី)",
  ],
  cd_kind: ["Kind", "ប្រភេទ"],
  cd_what: ["What", "អ្វី"],
  cd_cur: ["Currency", "រូបិយប័ណ្ណ"],
  cd_amount: ["Amount", "ចំនួន"],
  cd_add: ["Add a line", "បន្ថែមជួរ"],
  cd_remove: ["Remove line {0}", "លុបជួរ {0}"],
  cd_line: ["Line {0}", "ជួរ {0}"],
  cd_receipt: [
    "Keep the receipt. A Manager checks it before the Expense report is made.",
    "រក្សាបង្កាន់ដៃ។ អ្នកគ្រប់គ្រងពិនិត្យវា មុនបង្កើតរបាយការណ៍ចំណាយ។",
  ],
  e_amount_usd: ["Type dollars, like 12.50.", "វាយជាដុល្លារ ដូចជា 12.50។"],
  e_amount_khr: ["Type whole riel, like 40000.", "វាយជារៀលគត់ ដូចជា 40000។"],
  e_lines: [
    "Add at least one line, or tick No cost.",
    "បន្ថែមយ៉ាងហោចណាស់មួយជួរ ឬធីក គ្មានថ្លៃ។",
  ],
  ck_t: ["Check the repair cost of {0}", "ពិនិត្យថ្លៃជួសជុល {0}"],
  ck_makes: [
    "This makes an Expense report (money already spent) on 6050 Repairs and maintenance for {0}, one for each currency. It then waits for the normal Expense approval.",
    "នេះបង្កើតរបាយការណ៍ចំណាយ (ប្រាក់បានចំណាយរួច) លើ 6050 ការជួសជុល និងថែទាំ សម្រាប់ {0} មួយសម្រាប់រូបិយប័ណ្ណនីមួយៗ។ បន្ទាប់មកវារង់ចាំការអនុម័តចំណាយធម្មតា។",
  ],
  ck_rate: [
    "Riel turns into dollars at today's riel rate.",
    "រៀលប្តូរជាដុល្លារតាមអត្រាប្តូរប្រាក់ថ្ងៃនេះ។",
  ],
  ck_paid: ["Paid with", "បង់ដោយ"],
  ck_OWN_MONEY: [
    "Staff's own money (paid back later)",
    "ប្រាក់ផ្ទាល់ខ្លួនបុគ្គលិក (សងវិញពេលក្រោយ)",
  ],
  ck_CASH: ["Petty cash (1030)", "សាច់ប្រាក់រាយ (1030)"],
  ck_day: ["Day the money was spent", "ថ្ងៃចំណាយប្រាក់"],
  ck_receipt: [
    "I have seen the receipt and it matches these lines.",
    "ខ្ញុំបានឃើញបង្កាន់ដៃ ហើយវាត្រូវនឹងជួរទាំងនេះ។",
  ],
  e_receipt: ["Check the receipt first.", "សូមពិនិត្យបង្កាន់ដៃជាមុនសិន។"],
  ck_done: [
    "{0}: cost checked. Expense report {1} made.",
    "{0}៖ បានពិនិត្យថ្លៃ។ បានបង្កើតរបាយការណ៍ចំណាយ {1}។",
  ],
  est_WAITING: ["Waiting for approval", "រង់ចាំការអនុម័ត"],
  est_APPROVED: ["Approved", "បានអនុម័ត"],
  est_REFUSED: ["Not approved", "មិនបានអនុម័ត"],
  est_PAID_OUT: ["Advance given", "បានផ្ដល់ប្រាក់បុរេប្រទាន"],
  est_DONE: ["Posted", "បានកត់ត្រា"],
  est_VOID: ["Void", "ទុកជាមោឃៈ"],
  h_COST_ENTERED: ["Repair cost typed", "បានវាយថ្លៃជួសជុល"],
  h_COST_CHECKED: [
    "Repair cost checked; Expense report {0}",
    "បានពិនិត្យថ្លៃជួសជុល៖ របាយការណ៍ចំណាយ {0}",
  ],
  m_title: ["Monthly report", "របាយការណ៍ប្រចាំខែ"],
  m_sub: [
    "One month of problem reports and what the repairs cost. Dollars and riel are shown apart.",
    "របាយការណ៍បញ្ហាមួយខែ និងថ្លៃជួសជុល។ ដុល្លារ និងរៀល បង្ហាញដាច់ពីគ្នា។",
  ],
  m_month: ["Month", "ខែ"],
  m_right: [
    "You need the right Plan repairs to see the Monthly report.",
    "អ្នកត្រូវមានសិទ្ធិ រៀបចំការជួសជុល ដើម្បីមើលរបាយការណ៍ប្រចាំខែ។",
  ],
  m_received: ["Reports received", "របាយការណ៍ដែលបានទទួល"],
  m_received_s: ["{0} Unit · {1} Building", "{0} បន្ទប់ · {1} អគារ"],
  m_joined: ["{0} joined, not counted again", "{0} បានភ្ជាប់ មិនរាប់ម្ដងទៀត"],
  m_done: ["Done", "រួចរាល់"],
  m_days: ["{0} days to fix on average", "ជាមធ្យម {0} ថ្ងៃដើម្បីជួសជុល"],
  m_open: ["Still open", "នៅបើក"],
  m_open_s: [
    "{0} opened again · {1} not accepted",
    "{0} បានបើកម្ដងទៀត · {1} មិនទទួលយក",
  ],
  m_on_time: ["Urgent fixed on time", "បន្ទាន់ ជួសជុលទាន់ពេល"],
  m_on_time_s: [
    "Normal planned on time: {0} / {1}",
    "ធម្មតា រៀបចំទាន់ពេល៖ {0} / {1}",
  ],
  m_pays: [
    "Owner pays {0} · Tenant pays {1} · Damage charges {2}",
    "ម្ចាស់បង់ {0} · អ្នកជួលបង់ {1} · ថ្លៃខូចខាត {2}",
  ],
  m_cost_unit: ["Repair cost by Unit", "ថ្លៃជួសជុលតាមបន្ទប់"],
  m_cost_type: ["Repair cost by type", "ថ្លៃជួសជុលតាមប្រភេទ"],
  m_no_cost: ["No repair done this month.", "ខែនេះគ្មានការជួសជុលរួចរាល់ទេ។"],
  m_where: ["Where", "ទីកន្លែង"],
  m_reports: ["Reports", "របាយការណ៍"],
  m_building: ["Building (shared places)", "អគារ (កន្លែងរួម)"],
  m_repeats: [
    "Same problem again in one Unit",
    "បញ្ហាដដែលម្ដងទៀតក្នុងបន្ទប់តែមួយ",
  ],
  m_none: ["None this month.", "ខែនេះគ្មានទេ។"],
  m_times: ["{0} times:", "{0} ដង៖"],
  m_by_type: ["Reports by type", "របាយការណ៍តាមប្រភេទ"],
  m_by_place: ["Reports by place", "របាយការណ៍តាមទីកន្លែង"],
  m_late: ["Late now", "យឺតឥឡូវនេះ"],
  fi_from: [
    "From the move-out inspection of {0}, finding {1}. The Unit and the text come from the finding; you may change the text.",
    "ពីការត្រួតពិនិត្យពេលចាកចេញ ថ្ងៃ {0} ការរកឃើញទី {1}។ បន្ទប់ និងអត្ថបទ មកពីការរកឃើញ អ្នកអាចកែអត្ថបទបាន។",
  ],
  fi_has: [
    "This finding already has a Problem report:",
    "ការរកឃើញនេះមានរបាយការណ៍បញ្ហារួចហើយ៖",
  ],
  fi_replaced: [
    "This inspection was replaced by a newer one. Make the report from a finding of the newer inspection.",
    "ការត្រួតពិនិត្យនេះត្រូវបានជំនួសដោយការត្រួតពិនិត្យថ្មី។ សូមបង្កើតរបាយការណ៍ពីការរកឃើញនៃការត្រួតពិនិត្យថ្មី។",
  ],
  fi_missing: [
    "This inspection finding was not found.",
    "រកមិនឃើញការរកឃើញនៃការត្រួតពិនិត្យនេះទេ។",
  ],
  fi_link: [
    "From the move-out inspection of {0}: {1}",
    "ពីការត្រួតពិនិត្យពេលចាកចេញ ថ្ងៃ {0}៖ {1}",
  ],
  fi_open: ["Open the move-out", "បើកការចាកចេញ"],
  // DL-222: a problem reported at a short-stay room check.
  st_link: [
    "From the room check after short stay {0} ({1}, {2} to {3}).",
    "ពីការពិនិត្យបន្ទប់ក្រោយការស្នាក់នៅខ្លី {0} ({1}, {2} ដល់ {3})។",
  ],
  st_open: ["Open the stay", "បើកការស្នាក់នៅ"],
} as const satisfies Record<string, readonly [string, string]>;

export type ProblemsTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function pt(
  language: Language,
  key: ProblemsTextKey,
  ...values: (string | number)[]
): string {
  const words: string = TEXT[key][language === "km" ? 1 : 0];
  return words.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

/** A history step has its own words; an unknown step shows as it is. */
export function hasText(key: string): key is ProblemsTextKey {
  return key in TEXT;
}
