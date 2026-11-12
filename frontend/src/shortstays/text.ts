// Daily and weekly rent: the words of Tenants › Short stays, in English and Khmer, from the
// mock-up rounds 28, 31 and 35 (DESIGN.md "Short stays"). Khmer marked "new" is not in the
// mock-up and needs the native check.

import type { Language } from "../signInText";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: ["This could not be read just now.", "មិនអាចអានបានទេឥឡូវនេះ។"],
  retry: ["Try again", "សាកម្តងទៀត"],
  no_property: ["Choose a Property first.", "សូមជ្រើសអចលនទ្រព្យជាមុន។"],
  // new
  back: ["Back to Short stays", "ត្រឡប់ទៅការស្នាក់នៅខ្លី"],
  // new
  not_found: ["This booking was not found.", "រកមិនឃើញការកក់នេះទេ។"],
  required: ["required", "ចាំបាច់"],
  cancel: ["Cancel", "បោះបង់"],
  // Page
  sub: [
    "Daily and weekly guests in vacant Units. Full payment before check-in.",
    // new
    "ភ្ញៀវប្រចាំថ្ងៃ និងប្រចាំសប្ដាហ៍ក្នុងបន្ទប់ទំនេរ។ បង់ពេញមុនពេលចូល។",
  ],
  add: ["New booking", "ការកក់ថ្មី"],
  tabs: ["Views", "ទិដ្ឋភាព"],
  tab_cal: ["Calendar", "ប្រតិទិន"],
  tab_list: ["Bookings", "ការកក់"],
  prev: ["Earlier", "មុន"],
  next: ["Later", "បន្ទាប់"],
  this_week: ["Today", "ថ្ងៃនេះ"],
  c_unit: ["Unit", "បន្ទប់"],
  lease: ["Lease", "កិច្ចសន្យា"],
  reserved: ["Reserved", "បានកក់ទុក"],
  not_for_rent: ["Not for rent", "មិនជួល"],
  cal_none: ["There are no Units yet.", "មិនទាន់មានបន្ទប់នៅឡើយទេ។"],
  // List
  c_no: ["No.", "លេខ"],
  c_guest: ["Guest", "ភ្ញៀវ"],
  c_dates: ["Stay", "ការស្នាក់នៅ"],
  c_total: ["Total", "សរុប"],
  c_status: ["Status", "ស្ថានភាព"],
  c_source: ["Booked by", "កក់តាម"],
  none: ["No bookings yet.", "មិនទាន់មានការកក់នៅឡើយទេ។"],
  n1: ["1 booking", "ការកក់ 1"],
  n: ["{0} bookings", "ការកក់ {0}"],
  nights1: ["1 night", "1 យប់"],
  nights: ["{0} nights", "{0} យប់"],
  st_BOOKED: ["Booked", "បានកក់"],
  st_CHECKED_IN: ["Checked in", "បានចូល"],
  st_CHECKED_OUT: ["Checked out", "បានចេញ"],
  st_CANCELLED: ["Cancelled", "បានលុបចោល"],
  st_NO_SHOW: ["No-show", "មិនបានមក"],
  src_WALK_IN: ["Walk-in", "មកផ្ទាល់"],
  src_PHONE: ["Phone", "ទូរស័ព្ទ"],
  src_TELEGRAM: ["Telegram", "តេឡេក្រាម"],
  src_WEBSITE: ["Website", "គេហទំព័រ"],
  src_BOOKING_SITE: ["Booking site", "គេហទំព័រកក់"],
  // New booking
  new_sub: [
    "Pick the Unit and the nights. The price follows the rules in Settings.",
    // new
    "ជ្រើសបន្ទប់ និងយប់។ តម្លៃគិតតាមច្បាប់ក្នុងការកំណត់។",
  ],
  f_unit: ["Unit", "បន្ទប់"],
  f_in: ["Check-in", "ថ្ងៃចូល"],
  f_out: ["Check-out", "ថ្ងៃចេញ"],
  f_guests: ["Guests", "ចំនួនភ្ញៀវ"],
  f_source: ["Booked by", "កក់តាម"],
  f_site: ["Booking site", "គេហទំព័រកក់"],
  f_ref: ["Booking-site number", "លេខកក់របស់គេហទំព័រ"],
  f_note: ["Note", "កំណត់ចំណាំ"],
  f_guest: ["Guest", "ភ្ញៀវ"],
  f_find: ["Find a guest by name or phone", "ស្វែងរកភ្ញៀវតាមឈ្មោះ ឬទូរស័ព្ទ"],
  // new (owner test 06/11/2026): Customers who match the typed name or phone.
  g_matches: [
    "Already a Customer? Choose them instead of adding again:",
    // new
    "ជាអតិថិជនរួចហើយ? ជ្រើសពួកគេជំនួសការបន្ថែមម្តងទៀត៖",
  ],
  f_found_none: [
    "No Customer has this name or phone. Add the guest below.",
    // new
    "គ្មានអតិថិជនមានឈ្មោះ ឬទូរស័ព្ទនេះទេ។ បន្ថែមភ្ញៀវខាងក្រោម។",
  ],
  f_new_guest: ["New guest", "ភ្ញៀវថ្មី"],
  f_name: [
    "Full name (as on the ID or passport)",
    "ឈ្មោះពេញ (ដូចអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែន)",
  ],
  f_phone: ["Phone", "ទូរស័ព្ទ"],
  pick: ["Choose…", "ជ្រើសរើស…"],
  save: ["Book", "កក់"],
  saving: ["Booking…", "កំពុងកក់…"],
  // Price box
  p_title: ["Price", "តម្លៃ"],
  p_pick: [
    "Pick a Unit and the nights to see the price.",
    // new
    "ជ្រើសបន្ទប់ និងយប់ ដើម្បីមើលតម្លៃ។",
  ],
  l_NIGHTS: ["{0} × night {1}", "{0} × យប់ {1}"],
  l_WEEKS: ["{0} × week {1}", "{0} × សប្ដាហ៍ {1}"],
  off: ["{0}% off", "បញ្ចុះ {0}%"],
  total: ["Total to pay before check-in", "សរុបត្រូវបង់មុនពេលចូល"],
  as_weeks: [
    "Charged as whole weeks: a stay never costs more than the next whole week.",
    // new
    "គិតជាសប្ដាហ៍ពេញ៖ ការស្នាក់នៅមិនដែលថ្លៃជាងសប្ដាហ៍ពេញបន្ទាប់ទេ។",
  ],
  hint: [
    "This stay costs more than the 1-month-only rent of {0}. Offer the monthly Lease.",
    // new
    "ការស្នាក់នៅនេះថ្លៃជាងថ្លៃជួលតែ 1 ខែ {0}។ ស្នើកិច្ចសន្យាប្រចាំខែ។",
  ],
  b_PAST: ["The check-in day has passed.", "ថ្ងៃចូលបានកន្លងផុតហើយ។"],
  b_BOOKED: [
    "Another guest has booked one of these nights.",
    // new
    "ភ្ញៀវផ្សេងបានកក់យប់មួយក្នុងចំណោមយប់ទាំងនេះ។",
  ],
  b_LEASE: [
    "A Lease covers one of these nights.",
    // new
    "កិច្ចសន្យាជួលគ្របដណ្តប់យប់មួយក្នុងចំណោមយប់ទាំងនេះ។",
  ],
  b_RESERVED: [
    "The Unit is reserved for a tenant.",
    // new
    "បន្ទប់នេះបានកក់ទុកសម្រាប់អ្នកជួល។",
  ],
  b_NOT_FOR_RENT: ["The Unit is not for rent.", "បន្ទប់នេះមិនជួលទេ។"],
  b_UNIT_UNDER_MAINTENANCE: [
    "The Unit is under maintenance.",
    "បន្ទប់កំពុងជួសជុល។",
  ],
  b_UNIT_OUT_OF_SERVICE: ["The Unit is out of service.", "បន្ទប់ឈប់ប្រើ។"],
  p_too_long: [
    "A short stay is at most 29 nights. A longer stay is a Lease.",
    // new
    "ការស្នាក់នៅខ្លីមិនលើសពី 29 យប់ទេ។ ការស្នាក់នៅយូរជាងនេះគឺកិច្ចសន្យាជួល។",
  ],
  p_no_rent: [
    "This Unit has no monthly Rent, so it has no short-stay price.",
    // new
    "បន្ទប់នេះគ្មានថ្លៃជួលប្រចាំខែ ដូច្នេះគ្មានតម្លៃស្នាក់នៅខ្លីទេ។",
  ],
  // Errors
  e_sum1: ["1 thing needs fixing:", "មាន 1 ចំណុចត្រូវកែ៖"],
  e_sum: ["{0} things need fixing:", "មាន {0} ចំណុចត្រូវកែ៖"],
  e_unit: ["Choose the Unit.", "ជ្រើសបន្ទប់។"],
  e_dates: [
    "The check-out day is after the check-in day.",
    "ថ្ងៃចេញត្រូវនៅក្រោយថ្ងៃចូល។",
  ],
  e_guest: [
    "Choose the guest or add a new one.",
    "ជ្រើសភ្ញៀវ ឬបន្ថែមភ្ញៀវថ្មី។",
  ],
  e_site: ["Name the booking site.", "ដាក់ឈ្មោះគេហទំព័រកក់។"],
  e_guests: ["Guests are 1 to 10.", "ភ្ញៀវពី 1 ដល់ 10 នាក់។"],
  e_free: [
    "These nights cannot be booked in this Unit.",
    // new
    "យប់ទាំងនេះមិនអាចកក់ក្នុងបន្ទប់នេះបានទេ។",
  ],
  f_right: [
    "Your account may not make bookings.",
    // new
    "គណនីរបស់អ្នកមិនអាចធ្វើការកក់បានទេ។",
  ],
  f_taken: [
    "Someone has just booked one of these nights. Pick other nights or another Unit.",
    // new
    "មាននរណាម្នាក់ទើបតែកក់យប់មួយក្នុងចំណោមនេះ។ ជ្រើសយប់ផ្សេង ឬបន្ទប់ផ្សេង។",
  ],
  f_refused: [
    "The server refused this booking. Check what you typed.",
    // new
    "ម៉ាស៊ីនមេបានបដិសេធការកក់នេះ។ ពិនិត្យអ្វីដែលអ្នកបានវាយ។",
  ],
  f_why: [
    "This booking was not made: {0}",
    // new
    "ការកក់នេះមិនបានធ្វើទេ៖ {0}",
  ],
  f_failed: [
    "This was not saved. Check the connection and try again.",
    "មិនបានរក្សាទុកទេ។ ពិនិត្យការតភ្ជាប់ ហើយសាកម្តងទៀត។",
  ],
  // Booking
  made: ["Booking {0} made.", "បានធ្វើការកក់ {0}។"],
  d_stay: ["Stay", "ការស្នាក់នៅ"],
  d_guest: ["Guest", "ភ្ញៀវ"],
  d_guests: ["Guests", "ចំនួនភ្ញៀវ"],
  d_phone: ["Phone", "ទូរស័ព្ទ"],
  d_dates: ["{0} to {1}", "{0} ដល់ {1}"],
  d_price: ["Price", "តម្លៃ"],
  d_hist: ["History", "ប្រវត្តិ"],
  ev_BOOKED: ["Booked", "បានកក់"],
  // Step 3: payment, deposit, check-in, check-out, room check, damage. All new.
  cal_unpaid: ["Not paid", "មិនទាន់បង់"],
  pay_t: ["Payment", "ការបង់ប្រាក់"],
  pay_NOT_BILLED: ["Not billed yet", "មិនទាន់ចេញវិក្កយបត្រ"],
  pay_UNPAID: ["Not paid", "មិនទាន់បង់"],
  pay_PARTIALLY_PAID: ["Partly paid", "បានបង់ខ្លះ"],
  pay_PAID: ["Paid", "បានបង់"],
  pay_PAID_ON_SITE: ["Paid on the booking site", "បានបង់លើគេហទំព័រកក់"],
  bill: ["Make the Invoice", "ចេញវិក្កយបត្រ"],
  bill_s: [
    "Full payment before check-in. The guest pays the Invoice on Receive payment, which makes the Receipt.",
    "បង់ពេញមុនពេលចូល។ ភ្ញៀវបង់វិក្កយបត្រនៅទទួលការបង់ប្រាក់ ដែលចេញបង្កាន់ដៃ។",
  ],
  on_site: ["Paid on the booking site", "បានបង់លើគេហទំព័រកក់"],
  on_site_s: [
    "The guest paid {0}. No Invoice is made, so nothing is paid twice.",
    "ភ្ញៀវបានបង់ {0}។ មិនចេញវិក្កយបត្រទេ ដូច្នេះមិនបង់ពីរដង។",
  ],
  receive: ["Receive payment", "ទទួលការបង់ប្រាក់"],
  open_inv: ["Open Invoice {0}", "បើកវិក្កយបត្រ {0}"],
  dep_t: ["Deposit", "ប្រាក់កក់"],
  dep_none: [
    "No deposit yet. Every guest leaves a cash deposit or a card hold.",
    "មិនទាន់មានប្រាក់កក់ទេ។ ភ្ញៀវគ្រប់រូបទុកប្រាក់កក់ជាសាច់ប្រាក់ ឬការរក្សាទុកលើកាត។",
  ],
  dep_CASH: ["Cash deposit", "ប្រាក់កក់សាច់ប្រាក់"],
  dep_CARD_HOLD: ["Card hold", "រក្សាទុកលើកាត"],
  dep_ref: [
    "Hold reference from the card machine",
    "លេខយោងការរក្សាទុកពីម៉ាស៊ីនកាត",
  ],
  dep_last4: [
    "Card's last 4 digits (if wanted)",
    "លេខ 4 ខ្ទង់ចុងក្រោយនៃកាត (បើចង់)",
  ],
  dep_never: ["Never type the card number.", "កុំវាយលេខកាតឲ្យសោះ។"],
  dep_take: ["Take the deposit", "ទទួលប្រាក់កក់"],
  dep_HELD: ["Held", "កំពុងរក្សាទុក"],
  dep_RETURNED: ["Returned", "បានប្រគល់វិញ"],
  dep_KEPT: ["Kept {0}", "បានទុក {0}"],
  dep_end: ["Return the deposit", "ប្រគល់ប្រាក់កក់វិញ"],
  dep_end_keep: [
    "Keep {0} for damage, return {1}",
    "ទុក {0} សម្រាប់ការខូចខាត ប្រគល់ {1} វិញ",
  ],
  dep_wait: [
    "The deposit ends after check-out and the room check, once the damage charge is decided.",
    "ប្រាក់កក់បញ្ចប់ក្រោយចេញ និងពិនិត្យបន្ទប់ ពេលសម្រេចថ្លៃខូចខាតរួច។",
  ],
  in_t: ["Check-in", "ការចូល"],
  in_paid: ["The stay is paid", "ការស្នាក់នៅបានបង់"],
  in_deposit: ["The deposit is taken", "បានទទួលប្រាក់កក់"],
  in_id: [
    "The ID or passport number is on the Customer",
    "លេខអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែនមាននៅលើអតិថិជន",
  ],
  in_day: ["It is the check-in day ({0})", "ដល់ថ្ងៃចូល ({0})"],
  in_room: ["The room is ready", "បន្ទប់រួចរាល់"],
  in_copy: [
    "I made a copy of the ID or passport",
    "ខ្ញុំបានថតចម្លងអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែន",
  ],
  in_rules: [
    "The guest signed the house rules",
    "ភ្ញៀវបានចុះហត្ថលេខាលើបទបញ្ជាផ្ទះ",
  ],
  in_b: ["Check in", "ចូល"],
  out_t: ["Check-out", "ការចេញ"],
  out_s: [
    "The Unit is Cleaning until the room check is done.",
    "បន្ទប់កំពុងសម្អាតរហូតដល់ពិនិត្យបន្ទប់រួច។",
  ],
  out_b: ["Check out", "ចេញ"],
  room_t: ["Room check", "ពិនិត្យបន្ទប់"],
  room_due: ["Room check due on {0}.", "ត្រូវពិនិត្យបន្ទប់នៅថ្ងៃ {0}។"],
  room_done: ["Room checked {0}.", "បានពិនិត្យបន្ទប់ {0}។"],
  // DL-222: the room check reports problems (Problem reports), never a cost. Khmer is new.
  room_problems: ["Problems found", "បញ្ហាដែលរកឃើញ"],
  room_hint: [
    "Report each problem. It becomes a Problem report of the Unit. The charge is set on the booking later.",
    "រាយការណ៍បញ្ហានីមួយៗ។ វាក្លាយជារបាយការណ៍បញ្ហារបស់បន្ទប់។ ថ្លៃត្រូវកំណត់លើការកក់ពេលក្រោយ។",
  ],
  room_add: ["Report a problem", "រាយការណ៍បញ្ហា"],
  room_type: ["Type", "ប្រភេទ"],
  room_pick: ["Pick the type", "ជ្រើសរើសប្រភេទ"],
  room_wrong: ["What is wrong", "មានបញ្ហាអ្វី"],
  room_urgent: ["Urgent", "បន្ទាន់"],
  room_remove: ["Remove", "ដកចេញ"],
  room_no_right: [
    "To report a problem, your account needs the right to add a Problem report.",
    "ដើម្បីរាយការណ៍បញ្ហា គណនីរបស់អ្នកត្រូវមានសិទ្ធិបន្ថែមរបាយការណ៍បញ្ហា។",
  ],
  room_note: ["Note", "កំណត់ចំណាំ"],
  room_b: ["Room check done", "ពិនិត្យបន្ទប់រួច"],
  e_type: ["Pick the type of problem.", "សូមជ្រើសរើសប្រភេទបញ្ហា។"],
  e_wrong: ["Say what is wrong.", "សូមប្រាប់ថាមានបញ្ហាអ្វី។"],
  e_cost: [
    "Type the cost in dollars, for example 80 or 80.50.",
    "វាយតម្លៃជាដុល្លារ ឧទាហរណ៍ 80 ឬ 80.50។",
  ],
  dmg_t: ["Damage", "ការខូចខាត"],
  dmg_problems: ["Problems from the room check", "បញ្ហាពីការពិនិត្យបន្ទប់"],
  dmg_due: [
    "Decide the damage charge. The deposit waits until then.",
    "សូមសម្រេចថ្លៃខូចខាត។ ប្រាក់កក់រង់ចាំរហូតដល់ពេលនោះ។",
  ],
  dmg_wait: [
    "The damage charge is not decided yet. A person who bills damage decides it.",
    "ថ្លៃខូចខាតមិនទាន់សម្រេចទេ។ អ្នកដែលចេញវិក្កយបត្រខូចខាតជាអ្នកសម្រេច។",
  ],
  dmg_charge: ["Charge the guest", "គិតថ្លៃភ្ញៀវ"],
  dmg_none: ["No charge", "មិនគិតថ្លៃ"],
  dmg_for: ["What the guest pays for", "ភ្ញៀវបង់សម្រាប់អ្វី"],
  dmg_amount: ["Amount (US$)", "ចំនួនទឹកប្រាក់ (ដុល្លារ)"],
  dmg_note_opt: ["Note (if wanted)", "កំណត់ចំណាំ (បើចង់)"],
  dmg_save: ["Save the decision", "រក្សាទុកការសម្រេច"],
  dmg_rule: [
    "The charge comes from the deposit first. The rest is a Damage Invoice for the guest.",
    "ថ្លៃត្រូវយកពីប្រាក់កក់មុន។ ចំនួននៅសល់ជាវិក្កយបត្រខូចខាតសម្រាប់ភ្ញៀវ។",
  ],
  dmg_no_charge: ["No damage charge.", "មិនគិតថ្លៃការខូចខាត។"],
  e_for: ["Say what the guest pays for.", "សូមប្រាប់ថាភ្ញៀវបង់សម្រាប់អ្វី។"],
  dmg_WAITING: ["Waits for a decision", "រង់ចាំការសម្រេច"],
  dmg_APPROVED: ["Charged", "បានគិតថ្លៃ"],
  dmg_REFUSED: ["No charge", "មិនគិតថ្លៃ"],
  dmg_from: ["{0} from the deposit", "{0} ពីប្រាក់កក់"],
  dmg_inv: ["Invoice {0} for the rest", "វិក្កយបត្រ {0} សម្រាប់ចំនួនដែលនៅសល់"],
  dmg_note: ["Reason", "មូលហេតុ"],
  dmg_ok: ["Charge the guest", "គិតថ្លៃភ្ញៀវ"],
  dmg_no: ["No charge", "មិនគិតថ្លៃ"],
  e_reason: ["No charge says why.", "មិនគិតថ្លៃត្រូវប្រាប់មូលហេតុ។"],
  // new
  dd_t: [
    "{0} stay(s) wait for a damage decision. Open each booking and choose Charge the guest or No charge.",
    "ការស្នាក់នៅ {0} រង់ចាំការសម្រេចថ្លៃខូចខាត។ បើកការកក់នីមួយៗ ហើយជ្រើស គិតថ្លៃភ្ញៀវ ឬ មិនគិតថ្លៃ។",
  ],
  // new
  dd_row: ["{0}, {1}: problems {2}", "{0}, {1}៖ បញ្ហា {2}"],
  f_stale: [
    "This booking changed meanwhile. It is shown as it is now.",
    "ការកក់នេះបានផ្លាស់ប្តូរ។ វាត្រូវបានបង្ហាញដូចឥឡូវនេះ។",
  ],
  f_step_right: [
    "Your account may not do this step.",
    "គណនីរបស់អ្នកមិនអាចធ្វើជំហាននេះបានទេ។",
  ],
  f_step_refused: [
    "The server refused this step. Check what you typed.",
    "ម៉ាស៊ីនមេបានបដិសេធជំហាននេះ។ ពិនិត្យអ្វីដែលអ្នកបានវាយ។",
  ],
  f_not_now: [
    "This cannot be done now. The booking is shown as it is now.",
    "មិនអាចធ្វើបានឥឡូវនេះទេ។ ការកក់ត្រូវបានបង្ហាញដូចឥឡូវនេះ។",
  ],
  ev_BILLED: ["Invoice made", "បានចេញវិក្កយបត្រ"],
  ev_PAID_ON_SITE: ["Paid on the booking site", "បានបង់លើគេហទំព័រកក់"],
  ev_DEPOSIT_TAKEN: ["Deposit taken", "បានទទួលប្រាក់កក់"],
  ev_CHECKED_IN: ["Checked in", "បានចូល"],
  ev_CHECKED_OUT: ["Checked out", "បានចេញ"],
  ev_ROOM_CHECKED: ["Room checked", "បានពិនិត្យបន្ទប់"],
  ev_DAMAGE_APPROVED: ["Damage approved", "បានអនុម័តការខូចខាត"],
  ev_DAMAGE_REFUSED: ["Damage refused", "បានបដិសេធការខូចខាត"],
  ev_DAMAGE_CHARGED: ["Damage charged", "បានគិតថ្លៃការខូចខាត"],
  ev_NO_DAMAGE_CHARGE: ["No damage charge", "មិនគិតថ្លៃការខូចខាត"],
  ev_DEPOSIT_RETURNED: ["Deposit returned", "បានប្រគល់ប្រាក់កក់វិញ"],
  ev_DEPOSIT_KEPT: [
    "Deposit kept for damage",
    "បានទុកប្រាក់កក់សម្រាប់ការខូចខាត",
  ],
  // Calendar squares and Unit types
  // new
  cal_free: ["Free", "ទំនេរ"],
  // new
  cal_in: ["In stay", "កំពុងស្នាក់"],
  // new
  cal_closed: ["Closed", "បិទ"],
  // new
  cal_book: ["New booking: {0}, night of {1}", "ការកក់ថ្មី៖ {0} យប់ថ្ងៃ {1}"],
  // new
  cal_days: ["{0} to {1}", "{0} ដល់ {1}"],
  t_STUDIO: ["Studio", "ស្ទូឌីយោ"],
  // new
  t_ONE_BEDROOM: ["1 bedroom", "1 បន្ទប់គេង"],
  // new
  t_TWO_BEDROOM: ["2 bedrooms", "2 បន្ទប់គេង"],
  // New booking, more
  // new
  f_nights: ["Nights", "ចំនួនយប់"],
  // new
  f_free_only: [
    "Only Units free on all these nights can be picked.",
    "អាចជ្រើសបានតែបន្ទប់ដែលទំនេរគ្រប់យប់ទាំងនេះ។",
  ],
  // new
  u_busy: ["not free", "មិនទំនេរ"],
  u_no_rent: [
    "no monthly Rent yet",
    // new
    "មិនទាន់មានថ្លៃជួលប្រចាំខែ",
  ],
  // new
  f_find_b: ["Find", "ស្វែងរក"],
  // new
  f_finding: ["Finding…", "កំពុងស្វែងរក…"],
  // new
  f_id: ["ID or passport number", "លេខអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែន"],
  // new
  g_choose: ["Choose", "ជ្រើស"],
  // new
  g_change: ["Change guest", "ប្តូរភ្ញៀវ"],
  // new
  g_add_new: ["Add a new guest", "បន្ថែមភ្ញៀវថ្មី"],
  // new
  g_no_right: [
    "Your account may not add Customers. Ask a Manager, or find a guest who is already a Customer.",
    "គណនីរបស់អ្នកមិនអាចបន្ថែមអតិថិជនបានទេ។ សូមសួរអ្នកគ្រប់គ្រង ឬស្វែងរកភ្ញៀវដែលជាអតិថិជនរួចហើយ។",
  ],
  // new
  g_same: [
    "This may be the same person. Use this Customer, or say it is another person.",
    "នេះប្រហែលជាមនុស្សតែមួយ។ ប្រើអតិថិជននេះ ឬបញ្ជាក់ថាជាមនុស្សផ្សេង។",
  ],
  // new
  g_use: ["Use this Customer", "ប្រើអតិថិជននេះ"],
  // new
  g_other: [
    "Another person: add the new guest",
    "មនុស្សផ្សេង៖ បន្ថែមភ្ញៀវថ្មី",
  ],
  // new
  g_id_used: [
    "Another Customer has this ID or passport number. Use that Customer.",
    "អតិថិជនផ្សេងមានលេខអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែននេះរួចហើយ។ សូមប្រើអតិថិជននោះ។",
  ],
  // new
  g_failed: [
    "The guest was not added. Check the connection and try again.",
    "មិនបានបន្ថែមភ្ញៀវទេ។ ពិនិត្យការតភ្ជាប់ ហើយសាកម្តងទៀត។",
  ],
  // new
  e_in: ["Choose the check-in day.", "ជ្រើសថ្ងៃចូល។"],
  // new
  e_nights: [
    "Type the nights: a whole number, 1 or more.",
    "វាយចំនួនយប់៖ ចំនួនគត់ ចាប់ពី 1 ឡើងទៅ។",
  ],
  // new
  e_name: ["Type the guest's full name.", "វាយឈ្មោះពេញរបស់ភ្ញៀវ។"],
  // new
  e_id: [
    "Type the ID or passport number.",
    "វាយលេខអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែន។",
  ],
  // Booking page, more
  // new
  d_unit: ["Unit", "បន្ទប់"],
  // new
  d_nights: ["Nights", "ចំនួនយប់"],
  // new
  d_source: ["Booked by", "កក់តាម"],
  // new
  d_site: ["Booking site", "គេហទំព័រកក់"],
  // new
  d_note: ["Note", "កំណត់ចំណាំ"],
  // new
  d_open_customer: ["Open Customer", "បើកអតិថិជន"],
  // Step 4a: fees, extend, cleaning
  d_times: [
    "Check-in from {0}, check-out by {1}",
    "ចូលចាប់ពីម៉ោង {0} ចេញមុនម៉ោង {1}",
  ],
  fee_t: ["Early check-in and late check-out", "ចូលមុនម៉ោង និងចេញយឺត"],
  fee_cost: ["{0} each for this stay.", "{0} ម្ដងៗ សម្រាប់ការស្នាក់នៅនេះ។"],
  fee_free: ["Free for this stay.", "ឥតគិតថ្លៃសម្រាប់ការស្នាក់នៅនេះ។"],
  fee_early: ["Add early check-in", "បន្ថែមការចូលមុនម៉ោង"],
  fee_late: ["Add late check-out (until {0})", "បន្ថែមការចេញយឺត (រហូតដល់ {0})"],
  fee_has_early: ["Early check-in added", "បានបន្ថែមការចូលមុនម៉ោង"],
  fee_has_late: [
    "Late check-out added (until {0})",
    "បានបន្ថែមការចេញយឺត (រហូតដល់ {0})",
  ],
  ext_t: ["Extend the stay", "បន្តការស្នាក់នៅ"],
  ext_out: ["New check-out day", "ថ្ងៃចេញថ្មី"],
  ext_b: ["Extend", "បន្ត"],
  ext_price: ["New total {0}: {1} more.", "សរុបថ្មី {0}៖ បន្ថែម {1}។"],
  ext_same: [
    "New total {0}: nothing more to pay.",
    "សរុបថ្មី {0}៖ មិនបាច់បង់បន្ថែមទេ។",
  ],
  ext_pricing: ["Pricing…", "កំពុងគិតតម្លៃ…"],
  ext_bill: [
    "The difference is a new Invoice for the guest.",
    "ចំនួនខុសគ្នាជាវិក្កយបត្រថ្មីសម្រាប់ភ្ញៀវ។",
  ],
  e_out: ["Pick a day after {0}.", "ជ្រើសថ្ងៃក្រោយ {0}។"],
  x_EXTEND: ["Extension", "ការបន្ត"],
  x_EARLY_CHECK_IN: ["Early check-in", "ការចូលមុនម៉ោង"],
  x_LATE_CHECK_OUT: ["Late check-out", "ការចេញយឺត"],
  pay_extra: ["{0}: Invoice {1}", "{0}៖ វិក្កយបត្រ {1}"],
  inv_UNPAID: ["Not paid", "មិនទាន់បង់"],
  inv_PARTIALLY_PAID: ["Partly paid", "បានបង់ខ្លះ"],
  inv_PAID: ["Paid", "បានបង់"],
  inv_VOID: ["Voided", "បានលុបចោល"],
  ev_EXTENDED: ["Stay extended", "បានបន្តការស្នាក់នៅ"],
  ev_EARLY_CHECK_IN: ["Early check-in added", "បានបន្ថែមការចូលមុនម៉ោង"],
  ev_LATE_CHECK_OUT: ["Late check-out added", "បានបន្ថែមការចេញយឺត"],
  tab_clean: ["Cleaning", "ការសម្អាត"],
  tab_sites: ["Booking sites", "គេហទំព័រកក់"],
  cl_prev: ["Day before", "ថ្ងៃមុន"],
  cl_next: ["Next day", "ថ្ងៃបន្ទាប់"],
  cl_none: [
    "Nothing to clean on this day.",
    "គ្មានអ្វីត្រូវសម្អាតនៅថ្ងៃនេះទេ។",
  ],
  cl_count: ["{0} to do", "{0} ត្រូវធ្វើ"],
  cl_DAILY_CLEAN: ["Daily clean", "សម្អាតប្រចាំថ្ងៃ"],
  cl_CHANGE_OVER: ["Change-over clean", "សម្អាតពេលប្ដូរភ្ញៀវ"],
  cl_ROOM_CHECK: ["Room check", "ពិនិត្យបន្ទប់"],
  cl_TO_DO: ["To do", "ត្រូវធ្វើ"],
  cl_DONE: ["Done", "រួចរាល់"],
  cl_SKIPPED: ["Skipped", "បានរំលង"],
  cl_late: ["Due {0}", "ត្រូវធ្វើ {0}"],
  cl_done_b: ["Done", "រួចរាល់"],
  cl_skip: ["Skip", "រំលង"],
  cl_reason: ["Why it is skipped", "មូលហេតុដែលរំលង"],
  cl_room: ["Do the room check", "ធ្វើការពិនិត្យបន្ទប់"],
  e_skip: ["A skipped clean says why.", "ការរំលងការសម្អាតត្រូវប្រាប់មូលហេតុ។"],
  cl_saved: ["{0}: {1}.", "{0}៖ {1}។"],
  // Step 4b: cancel and credit
  can_t: ["Cancel", "លុបចោល"],
  can_free: [
    "Free cancel until {0} at 23:59: the money paid comes back.",
    "លុបចោលដោយឥតគិតថ្លៃរហូតដល់ {0} ម៉ោង 23:59៖ ប្រាក់ដែលបានបង់នឹងបានមកវិញ។",
  ],
  can_late: [
    "Free cancel ended on {0}: the money paid is kept.",
    "ការលុបចោលដោយឥតគិតថ្លៃបានបញ្ចប់នៅ {0}៖ ប្រាក់ដែលបានបង់ត្រូវរក្សាទុក។",
  ],
  can_site: [
    "Paid on {0}: cancel there too, by the site's rules.",
    "បានបង់លើ {0}៖ លុបចោលនៅទីនោះផងដែរ តាមច្បាប់របស់គេហទំព័រ។",
  ],
  can_reason: ["Why", "មូលហេតុ"],
  can_b: ["Cancel the booking", "លុបចោលការកក់"],
  can_no_show: ["The guest did not come", "ភ្ញៀវមិនបានមក"],
  e_why: ["Say why.", "ប្រាប់មូលហេតុ។"],
  can_back: [
    "{0} is now the guest's Credit. Give it back with Refund below.",
    // new
    "{0} ឥឡូវជាឥណទានរបស់ភ្ញៀវ។ ប្រគល់វិញដោយប៊ូតុង សងប្រាក់ ខាងក្រោម។",
  ],
  can_open: ["Open the guest's credit", "បើកឥណទានរបស់ភ្ញៀវ"],
  // new (owner test 06/11/2026): the Refund button after a free cancel.
  rf_t: ["Give the money back", "ប្រគល់ប្រាក់វិញ"],
  rf_s: [
    "{0} goes back to the guest. A Manager or the Owner approves it in Waiting for approval.",
    // new
    "{0} ត្រឡប់ទៅភ្ញៀវវិញ។ អ្នកគ្រប់គ្រង ឬម្ចាស់អនុម័តក្នុង កំពុងរង់ចាំការអនុម័ត។",
  ],
  rf_method: ["How it goes back", "វិធីប្រគល់វិញ"],
  rf_note: ["Reference", "ឯកសារយោង"],
  rf_note_s: [
    "For example: Cash at the desk, or the ABA transaction number.",
    // new
    "ឧទាហរណ៍៖ សាច់ប្រាក់នៅតុ ឬលេខប្រតិបត្តិការ ABA។",
  ],
  e_rf_note: ["Type the reference.", "វាយឯកសារយោង។"],
  rf_b: ["Refund {0}", "សងប្រាក់ {0}"],
  rf_wait: [
    "Refund of {0} waits for approval.",
    // new
    "ការសងប្រាក់ {0} កំពុងរង់ចាំការអនុម័ត។",
  ],
  rf_open: ["Open Waiting for approval", "បើក កំពុងរង់ចាំការអនុម័ត"],
  rf_done: ["Given back: {0}.", "បានប្រគល់វិញ៖ {0}។"],
  rf_no_right: [
    "Your account may not make a Refund. Ask a Manager.",
    // new
    "គណនីរបស់អ្នកមិនអាចធ្វើការសងប្រាក់បានទេ។ សូមសួរអ្នកគ្រប់គ្រង។",
  ],
  can_kept: ["{0} is kept.", "{0} ត្រូវរក្សាទុក។"],
  can_nothing: ["No money was paid.", "មិនមានប្រាក់បានបង់ទេ។"],
  cr_t: ["Credit for a later stay", "ឥណទានសម្រាប់ការស្នាក់នៅពេលក្រោយ"],
  cr_s: [
    "Turn some or all of the kept money into credit, for a later stay or the first month of a Lease, when a room is free. Credit not used by its use-by day ends.",
    "ប្ដូរប្រាក់ដែលរក្សាទុកខ្លះ ឬទាំងអស់ទៅជាឥណទាន សម្រាប់ការស្នាក់នៅពេលក្រោយ ឬខែដំបូងនៃកិច្ចសន្យា នៅពេលមានបន្ទប់ទំនេរ។ ឥណទានដែលមិនបានប្រើត្រឹមថ្ងៃកំណត់ នឹងផុតសុពលភាព។",
  ],
  cr_amount: ["Credit (US$)", "ឥណទាន (US$)"],
  cr_note: ["Why", "មូលហេតុ"],
  cr_b: ["Give credit", "ផ្ដល់ឥណទាន"],
  cr_given: ["{0} credit, to use by {1}.", "ឥណទាន {0} ប្រើបានរហូតដល់ {1}។"],
  e_credit: ["Type an amount up to {0}.", "វាយចំនួនរហូតដល់ {0}។"],
  ev_CANCELLED: ["Cancelled", "បានលុបចោល"],
  ev_NO_SHOW: ["Did not come", "មិនបានមក"],
  ev_CREDIT_GIVEN: ["Credit given", "បានផ្ដល់ឥណទាន"],
  ev_CREDIT_ENDED: ["Credit ended", "ឥណទានបានផុតសុពលភាព"],
  cr_left: ["{0} left to use.", "នៅសល់ {0} ដែលអាចប្រើបាន។"],
  cr_end_s: [
    "The use-by day has passed. What is left of the credit becomes income.",
    "ថ្ងៃកំណត់បានកន្លងផុតហើយ។ ឥណទានដែលនៅសល់ក្លាយជាចំណូល។",
  ],
  cr_end_b: ["End credit", "បញ្ចប់ឥណទាន"],
  cr_ended: [
    "Credit ended: {0} became income (Invoice {1}).",
    "ឥណទានបានបញ្ចប់៖ {0} ក្លាយជាចំណូល (វិក្កយបត្រ {1})។",
  ],
  cr_ended_none: [
    "Credit ended on {0}. The guest had used all of it.",
    "ឥណទានបានបញ្ចប់នៅ {0}។ ភ្ញៀវបានប្រើអស់ហើយ។",
  ],
  cd_t: [
    "{0} guest credit(s) passed the use-by day. Open each booking and end the credit.",
    "ឥណទានភ្ញៀវ {0} បានហួសថ្ងៃកំណត់។ បើកការកក់នីមួយៗ ហើយបញ្ចប់ឥណទាន។",
  ],
  cd_row: ["{0}: {1} left, use by {2}", "{0}៖ នៅសល់ {1} ប្រើបានដល់ {2}"],
  ls_t: ["Change to a Lease", "ប្ដូរទៅកិច្ចសន្យាជួល"],
  ls_s: [
    "{0} off the first month when the guest signs a Lease. Make the guest's Lease draft, then link it here.",
    "បញ្ចុះ {0} លើខែដំបូង ពេលភ្ញៀវចុះហត្ថលេខាកិច្ចសន្យាជួល។ បង្កើតសេចក្ដីព្រាងកិច្ចសន្យារបស់ភ្ញៀវ រួចភ្ជាប់វានៅទីនេះ។",
  ],
  ls_none: [
    "The guest has no Lease draft yet.",
    "ភ្ញៀវមិនទាន់មានសេចក្ដីព្រាងកិច្ចសន្យាជួលទេ។",
  ],
  ls_pick: ["Lease draft", "សេចក្ដីព្រាងកិច្ចសន្យា"],
  ls_draft: ["{0}, from {1}, {2} a month", "{0} ចាប់ពី {1} {2} ក្នុងមួយខែ"],
  ls_new: ["New Lease", "កិច្ចសន្យាថ្មី"],
  ls_b: ["Link the Lease", "ភ្ជាប់កិច្ចសន្យា"],
  ls_linked: [
    "Linked to the Lease for {0}: {1} off the first month.",
    "បានភ្ជាប់ទៅកិច្ចសន្យាសម្រាប់ {0}៖ បញ្ចុះ {1} លើខែដំបូង។",
  ],
  ls_at_sign: [
    "Sign Lease asks for that much less.",
    "ការចុះហត្ថលេខាកិច្ចសន្យានឹងស្នើប្រាក់តិចជាងនោះ។",
  ],
  ls_signed: [
    "The Lease is signed with the money off.",
    "កិច្ចសន្យាបានចុះហត្ថលេខាជាមួយការបញ្ចុះតម្លៃ។",
  ],
  ls_open: ["Open the Lease", "បើកកិច្ចសន្យា"],
  ev_LEASE_LINKED: ["Lease linked", "បានភ្ជាប់កិច្ចសន្យា"],
  b_SITE_HOLD: [
    "Booked on {0}, {1} to {2}. Only a booking from {0} may take these nights.",
    "បានកក់នៅ {0} ពី {1} ដល់ {2}។ មានតែការកក់ពី {0} ទេ ដែលអាចយកយប់ទាំងនេះ។",
  ],
  cal_clash: [
    "{0} also has these nights: check both bookings.",
    "{0} ក៏មានយប់ទាំងនេះដែរ៖ ពិនិត្យការកក់ទាំងពីរ។",
  ],
  sc_s: [
    "Paste each room's calendar link (iCal or export link) from Booking.com, Agoda or Airbnb. The app reads it every 15 minutes and keeps those nights for that site.",
    "បិទភ្ជាប់តំណប្រតិទិន (iCal ឬតំណនាំចេញ) របស់បន្ទប់នីមួយៗពី Booking.com, Agoda ឬ Airbnb។ កម្មវិធីអានវារៀងរាល់ 15 នាទី ហើយរក្សាយប់ទាំងនោះសម្រាប់គេហទំព័រនោះ។",
  ],
  sc_none: ["No calendar links yet.", "មិនទាន់មានតំណប្រតិទិនទេ។"],
  sc_off: ["Off", "បិទ"],
  sc_waiting: ["Not read yet", "មិនទាន់អាន"],
  sc_ok: ["Read", "បានអាន"],
  sc_failed: ["Could not read", "មិនអាចអានបាន"],
  sc_read: [
    "Last read {0} · {1} booked ranges ahead",
    "អានចុងក្រោយ {0} · {1} ចន្លោះដែលបានកក់ខាងមុខ",
  ],
  sc_url: ["Calendar link", "តំណប្រតិទិន"],
  sc_save: ["Save link", "រក្សាទុកតំណ"],
  sc_cancel: ["Cancel", "បោះបង់"],
  sc_change: ["Change link", "ប្ដូរតំណ"],
  sc_turn_off: ["Turn off", "បិទ"],
  sc_turn_on: ["Turn on", "បើក"],
  sc_add: ["Add a calendar link", "បន្ថែមតំណប្រតិទិន"],
  sc_add_b: ["Add link", "បន្ថែមតំណ"],
  sc_taken: [
    "This room already has a link for that site.",
    "បន្ទប់នេះមានតំណសម្រាប់គេហទំព័រនោះរួចហើយ។",
  ],
  sc_bad: ["Check the link and try again.", "ពិនិត្យតំណ ហើយព្យាយាមម្ដងទៀត។"],
  e_link: [
    "A calendar link starts with https://",
    "តំណប្រតិទិនចាប់ផ្ដើមដោយ https://",
  ],
  e_link_form: [
    "Pick the room and the site, and paste a link that starts with https://",
    "ជ្រើសបន្ទប់ និងគេហទំព័រ ហើយបិទភ្ជាប់តំណដែលចាប់ផ្ដើមដោយ https://",
  ],
  // Step 5b (new): line names, thank-you, discount, guest history, review and quotes.
  l_EARLY_CHECK_IN: ["Early check-in", "ចូលមុនម៉ោង"],
  l_LATE_CHECK_OUT: ["Late check-out", "ចេញយឺត"],
  l_RETURNING_GUEST: [
    "Thank-you for a returning guest",
    "អរគុណភ្ញៀវដែលត្រឡប់មកវិញ",
  ],
  l_EXTRA_DISCOUNT: ["Extra discount", "បញ្ចុះតម្លៃបន្ថែម"],
  pay_due: ["To pay {0}", "ត្រូវបង់ {0}"],
  dc_t: ["Extra discount", "បញ្ចុះតម្លៃបន្ថែម"],
  dc_s: [
    "Owner or Manager only, before the Invoice. The guest sees it on the Invoice.",
    "សម្រាប់ម្ចាស់ ឬអ្នកគ្រប់គ្រងតែប៉ុណ្ណោះ មុនពេលចេញវិក្កយបត្រ។ ភ្ញៀវឃើញវានៅលើវិក្កយបត្រ។",
  ],
  dc_amount: ["Discount ($)", "ការបញ្ចុះតម្លៃ ($)"],
  dc_reason: ["Reason", "មូលហេតុ"],
  dc_b: ["Give the discount", "ផ្ដល់ការបញ្ចុះតម្លៃ"],
  dc_wrong: [
    "Type an amount less than the stay and a reason.",
    "វាយចំនួនទឹកប្រាក់តិចជាងតម្លៃស្នាក់នៅ និងមូលហេតុ។",
  ],
  dc_given: ["{0} off: {1}", "បញ្ចុះ {0}៖ {1}"],
  ev_DISCOUNT: ["Extra discount given", "បានផ្ដល់ការបញ្ចុះតម្លៃបន្ថែម"],
  ev_REVIEW_ASKED: ["Review asked for", "បានស្នើសុំការវាយតម្លៃ"],
  rv_t: ["Ask for a review", "ស្នើសុំការវាយតម្លៃ"],
  rv_s: [
    "Send this to the guest by Telegram, then mark it as asked. Ask once only.",
    "ផ្ញើសារនេះទៅភ្ញៀវតាម Telegram រួចសម្គាល់ថាបានស្នើ។ ស្នើតែម្ដងប៉ុណ្ណោះ។",
  ],
  // Mock-up round 31 (v73): the Google Maps review link of the owner's place.
  rv_message: [
    "Thank you for staying with CHETANA Residence, {0}! If you liked your stay, please leave us a short review on Google Maps: {1}",
    "អរគុណដែលបានស្នាក់នៅ CHETANA Residence {0}! បើអ្នកពេញចិត្ត សូមសរសេរការវាយតម្លៃខ្លីៗឱ្យយើងលើ Google Maps៖ {1}",
  ],
  rv_copy: ["Copy message", "ចម្លងសារ"],
  rv_copied: ["Copied.", "បានចម្លង។"],
  rv_b: ["Mark as asked", "សម្គាល់ថាបានស្នើ"],
  rv_done: ["Review asked for on {0}.", "បានស្នើសុំការវាយតម្លៃនៅ {0}។"],
  // DL-224 (new, owner's rules of 12/11/2026): Change Unit for a booking that is not checked in
  // yet, and the special discount after a move. The Khmer needs the native check.
  cu_t: ["Change Unit", "ប្ដូរបន្ទប់"],
  cu_s: [
    "Move the guest to another Unit before check-in. The guest keeps the agreed price of {0}.",
    "ផ្លាស់ភ្ញៀវទៅបន្ទប់ផ្សេងមុនពេលចូល។ ភ្ញៀវរក្សាតម្លៃដែលបានព្រមព្រៀង {0}។",
  ],
  cu_loading: ["Looking for free Units…", "កំពុងរកបន្ទប់ទំនេរ…"],
  cu_failed: [
    "The free Units could not be read just now.",
    "មិនអាចអានបន្ទប់ទំនេរបានទេឥឡូវនេះ។",
  ],
  cu_none: [
    "No other Unit is free on these nights.",
    "គ្មានបន្ទប់ផ្សេងទំនេរនៅយប់ទាំងនេះទេ។",
  ],
  cu_to: ["Move to", "ផ្លាស់ទៅ"],
  cu_same: ["Same type", "ប្រភេទដូចគ្នា"],
  cu_other: ["Other types", "ប្រភេទផ្សេង"],
  cu_other_note: [
    "This Unit is another type. The price stays the same. An Owner or Manager can give a special discount after the move.",
    "បន្ទប់នេះជាប្រភេទផ្សេង។ តម្លៃនៅដដែល។ ម្ចាស់ ឬអ្នកគ្រប់គ្រងអាចផ្ដល់ការបញ្ចុះតម្លៃពិសេសក្រោយពេលផ្លាស់។",
  ],
  cu_wrong: [
    "Choose a Unit and write the reason.",
    "សូមជ្រើសបន្ទប់ និងសរសេរមូលហេតុ។",
  ],
  cu_b: ["Move the guest", "ផ្លាស់ភ្ញៀវ"],
  cu_moved: [
    "Moved from {0} to {1}. The guest keeps the agreed price.",
    "បានផ្លាស់ពី {0} ទៅ {1}។ ភ្ញៀវរក្សាតម្លៃដែលបានព្រមព្រៀង។",
  ],
  cu_hist: ["{0} to {1}", "{0} ទៅ {1}"],
  cu_no_extend: [
    "A moved stay is not extended. Make a new booking for the extra nights.",
    "ការស្នាក់នៅដែលបានផ្លាស់បន្ទប់មិនអាចបន្តបានទេ។ សូមធ្វើការកក់ថ្មីសម្រាប់យប់បន្ថែម។",
  ],
  md_t: [
    "Special discount after the move",
    "បញ្ចុះតម្លៃពិសេសក្រោយពេលផ្លាស់បន្ទប់",
  ],
  md_s: [
    "Owner or Manager only, once for each move. If the stay is already paid, the amount becomes the guest's Credit.",
    "សម្រាប់ម្ចាស់ ឬអ្នកគ្រប់គ្រងតែប៉ុណ្ណោះ ម្ដងសម្រាប់ការផ្លាស់នីមួយៗ។ បើការស្នាក់នៅបានបង់រួច ចំនួននេះក្លាយជាឥណទានរបស់ភ្ញៀវ។",
  ],
  md_b: ["Give the special discount", "ផ្ដល់ការបញ្ចុះតម្លៃពិសេស"],
  md_credit: ["{0} is now the guest's Credit.", "{0} ឥឡូវជាឥណទានរបស់ភ្ញៀវ។"],
  ev_UNIT_CHANGED: ["Moved to another Unit", "បានផ្លាស់ទៅបន្ទប់ផ្សេង"],
  ev_MOVE_DISCOUNT: ["Special discount given", "បានផ្ដល់ការបញ្ចុះតម្លៃពិសេស"],
  gh_t: ["Guest", "ភ្ញៀវ"],
  gh_returning: ["Returning guest", "ភ្ញៀវត្រឡប់មកវិញ"],
  gh_problem: ["Problem guest", "ភ្ញៀវមានបញ្ហា"],
  gh_new: ["First stay", "ស្នាក់នៅលើកដំបូង"],
  gh_sum: [
    "{0} stays done · {1} nights · {2} spent",
    "ស្នាក់រួច {0} ដង · {1} យប់ · ចំណាយ {2}",
  ],
  gh_stays: ["Stays", "ការស្នាក់នៅ"],
  gh_notes: ["Notes", "កំណត់ចំណាំ"],
  gh_no_notes: ["No notes yet.", "មិនទាន់មានកំណត់ចំណាំទេ។"],
  gh_note: ["New note", "កំណត់ចំណាំថ្មី"],
  gh_mark: [
    "Problem guest (shows on every later booking)",
    "ភ្ញៀវមានបញ្ហា (បង្ហាញលើការកក់ក្រោយៗទាំងអស់)",
  ],
  gh_add: ["Add note", "បន្ថែមកំណត់ចំណាំ"],
  gh_empty: ["Write the note first.", "សូមសរសេរកំណត់ចំណាំជាមុន។"],
  nb_returning: [
    "Returning guest: {0} thank-you comes off a direct booking.",
    "ភ្ញៀវត្រឡប់មកវិញ៖ កាត់ {0} ជាការអរគុណលើការកក់ផ្ទាល់។",
  ],
  nb_problem: [
    "Problem guest. Read the notes before you book: {0}",
    "ភ្ញៀវមានបញ្ហា។ សូមអានកំណត់ចំណាំមុនពេលកក់៖ {0}",
  ],
  tab_quotes: ["Quotes", "សម្រង់តម្លៃ"],
  q_s: [
    "Today's price to send to a guest. A quote is not a promise: the price is set when the booking is made.",
    "តម្លៃថ្ងៃនេះសម្រាប់ផ្ញើទៅភ្ញៀវ។ សម្រង់តម្លៃមិនមែនជាការសន្យាទេ៖ តម្លៃត្រូវកំណត់ពេលធ្វើការកក់។",
  ],
  q_new: ["New quote", "សម្រង់តម្លៃថ្មី"],
  q_name: ["Guest name", "ឈ្មោះភ្ញៀវ"],
  q_contact: ["Telegram or phone", "Telegram ឬទូរស័ព្ទ"],
  q_guests: ["Guests", "ចំនួនភ្ញៀវ"],
  q_in: ["Check-in day", "ថ្ងៃចូល"],
  q_nights: ["Nights", "ចំនួនយប់"],
  q_b: ["Make the quote", "ធ្វើសម្រង់តម្លៃ"],
  q_wrong: [
    "Pick the room, type the guest's name, 1 to 10 guests and the nights.",
    "ជ្រើសបន្ទប់ វាយឈ្មោះភ្ញៀវ ភ្ញៀវ 1 ដល់ 10 នាក់ និងចំនួនយប់។",
  ],
  q_not_free: [
    "That room cannot be booked for those nights. Pick another room or other days.",
    "បន្ទប់នោះមិនអាចកក់សម្រាប់យប់ទាំងនោះបានទេ។ សូមជ្រើសបន្ទប់ ឬថ្ងៃផ្សេង។",
  ],
  q_none: ["No quotes yet.", "មិនទាន់មានសម្រង់តម្លៃទេ។"],
  q_made: [
    "Quote {0} made. Copy the message for the guest.",
    "បានធ្វើសម្រង់តម្លៃ {0}។ ចម្លងសារសម្រាប់ភ្ញៀវ។",
  ],
  q_book: ["Book this", "កក់បន្ទប់នេះ"],
  q_message: [
    "CHETANA Residence: quote {0}\nRoom {1}, {2} guests\n{3} to {4}, {5}\nTotal {6}\nCheck-in from {7}, check-out by {8}. Deposit {9} at check-in (cash or a card hold), given back after the room check.\nThis is today's price; the room is held only when you book.",
    "CHETANA Residence៖ សម្រង់តម្លៃ {0}\nបន្ទប់ {1} ភ្ញៀវ {2} នាក់\n{3} ដល់ {4} {5}\nសរុប {6}\nចូលចាប់ពីម៉ោង {7} ចេញមុនម៉ោង {8}។ ប្រាក់កក់ {9} ពេលចូល (សាច់ប្រាក់ ឬកាត) ហើយប្រគល់វិញក្រោយពិនិត្យបន្ទប់។\nនេះជាតម្លៃថ្ងៃនេះ បន្ទប់ត្រូវបានរក្សាទុកតែពេលអ្នកកក់ប៉ុណ្ណោះ។",
  ],
  // Step 5c (new): month prices on a quote, the weekly report and complaints.
  q_month: [
    "Staying longer? 1 month only: {0}. A Lease of 6 or 12 months: {1} a month.",
    "ស្នាក់យូរជាងនេះ? តែ 1 ខែ៖ {0}។ កិច្ចសន្យា 6 ឬ 12 ខែ៖ {1} ក្នុងមួយខែ។",
  ],
  tab_report: ["Weekly report", "របាយការណ៍ប្រចាំសប្ដាហ៍"],
  rp_sub: [
    "Occupancy and income per unit, after cleaning, laundry and booking-site costs.",
    "អត្រាមានអ្នកស្នាក់ និងចំណូលតាមបន្ទប់ ក្រោយដកថ្លៃសម្អាត បោកអ៊ុត និងកម្រៃគេហទំព័រកក់។",
  ],
  rp_week: ["Week {0} to {1}", "សប្ដាហ៍ {0} ដល់ {1}"],
  rp_so_far: ["so far", "រហូតមកដល់ពេលនេះ"],
  rp_prev: ["Week before", "សប្ដាហ៍មុន"],
  rp_next: ["Next week", "សប្ដាហ៍បន្ទាប់"],
  rp_occ: ["Occupancy", "អត្រាមានអ្នកស្នាក់"],
  rp_occ_s: [
    "{0} of {1} unit-nights paid · before the test {2}",
    "បានបង់ {0} ក្នុង {1} យប់-បន្ទប់ · មុនការសាកល្បង {2}",
  ],
  rp_net: ["Income after costs", "ចំណូលក្រោយដកថ្លៃ"],
  rp_net_s: ["Room income {0}", "ចំណូលបន្ទប់ {0}"],
  rp_lease: ["Guests who signed a Lease", "ភ្ញៀវដែលបានចុះកិច្ចសន្យា"],
  rp_lease_s: ["Try before you rent", "សាកមុនជួល"],
  rp_dmg: ["Damage and complaints", "ខូចខាត និងបណ្ដឹង"],
  rp_dmg_s: [
    "Damage: {0} · tenant complaints: {1}",
    "ខូចខាត៖ {0} · បណ្ដឹងពីអ្នកជួល៖ {1}",
  ],
  rp_nights: ["Paid nights", "យប់ដែលបានបង់"],
  rp_income: ["Room income", "ចំណូលបន្ទប់"],
  rp_site: ["Site fees", "កម្រៃគេហទំព័រ"],
  rp_clean: ["Cleaning", "សម្អាត"],
  rp_after: ["After costs", "ក្រោយដកថ្លៃ"],
  rp_all: ["All units", "បន្ទប់ទាំងអស់"],
  rp_note: [
    "Site fees are the booking-site share (0% until you set it in Settings). Cleaning covers cleaning and laundry: {0} per change-over, plus {1} for each towel and sheet change.",
    "កម្រៃគេហទំព័រ ជាចំណែករបស់គេហទំព័រកក់ (០% រហូតដល់អ្នកកំណត់ក្នុងការកំណត់)។ សម្អាត រួមទាំងសម្អាត និងបោកអ៊ុត៖ {0} ក្នុងមួយការប្ដូរភ្ញៀវ បូក {1} សម្រាប់ការប្ដូរកន្សែង និងកម្រាលម្ដងៗ។",
  ],
  rp_leases_t: ["Guests who signed a Lease", "ភ្ញៀវដែលបានចុះកិច្ចសន្យា"],
  rp_lease_row: [
    "{0} · Lease for {1} · {2} off",
    "{0} · កិច្ចសន្យាសម្រាប់ {1} · បញ្ចុះ {2}",
  ],
  rp_damage_t: ["Damage", "ខូចខាត"],
  rp_compl_t: ["Complaints from monthly tenants", "បណ្ដឹងពីអ្នកជួលប្រចាំខែ"],
  rp_src_t: ["Stays by booking source", "ការស្នាក់តាមប្រភពការកក់"],
  rp_cancel: [
    "Cancelled or did not come: {0} · money kept {1}",
    "បានលុបចោល ឬមិនបានមក៖ {0} · ប្រាក់រក្សាទុក {1}",
  ],
  rp_none: ["None this week.", "គ្មានក្នុងសប្ដាហ៍នេះទេ។"],
  rp_judge_t: ["How we judge the test", "របៀបវាយតម្លៃការសាកល្បង"],
  rp_judge: [
    "After 2 to 3 months, compare with {0} occupancy before the test. Then the Owner decides: keep, change or stop.",
    "ក្រោយ ២ ដល់ ៣ ខែ ប្រៀបធៀបជាមួយអត្រា {0} មុនការសាកល្បង។ បន្ទាប់មកម្ចាស់សម្រេច៖ បន្ត ប្ដូរ ឬឈប់។",
  ],
  rp_print: ["Print", "បោះពុម្ព"],
  cp_add: ["Record a complaint", "កត់ត្រាបណ្ដឹង"],
  cp_what: ["What happened", "អ្វីដែលបានកើតឡើង"],
  cp_unit: ["Tenant's Unit", "បន្ទប់អ្នកជួល"],
  cp_none_unit: ["Not one Unit", "មិនមែនបន្ទប់ណាមួយ"],
  cp_save: ["Save complaint", "រក្សាទុកបណ្ដឹង"],
  cp_empty: ["Write what happened first.", "សូមសរសេរអ្វីដែលបានកើតឡើងជាមុន។"],
} as const satisfies Record<string, readonly [string, string]>;

export type StaysTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function st(
  language: Language,
  key: StaysTextKey,
  ...values: (string | number)[]
): string {
  const words: string = TEXT[key][language === "km" ? 1 : 0];
  return words.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

export function hasText(key: string): key is StaysTextKey {
  return key in TEXT;
}
