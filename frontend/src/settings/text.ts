// V1-058 R7b: the words of Settings in English and Khmer, from the owner's mock-up (i18n4.js and
// later rounds). Khmer needs the native check before the app is used. Lines marked "new" are not
// in the mock-up.

import type { Language } from "../signInText";

const TEXT = {
  se_sub: [
    "Changed by the Owner, or by a user the Owner allows. Every change is dated and kept in History.",
    "ប្តូរដោយម្ចាស់ ឬអ្នកប្រើដែលម្ចាស់អនុញ្ញាត។ ការប្តូរនីមួយៗមានកាលបរិច្ឆេទ និងរក្សាក្នុងប្រវត្តិ។",
  ],
  set_who: [
    "Changes start from the date shown and never change Invoices or Receipts already made.",
    "ការប្តូរចាប់ផ្តើមពីថ្ងៃដែលបង្ហាញ ហើយមិនប្តូរវិក្កយបត្រ ឬបង្កាន់ដៃដែលបានធ្វើរួចទេ។",
  ],
  tabs: ["Settings tabs", "ផ្ទាំងការកំណត់"],
  se_tab_biz: ["Business", "អាជីវកម្ម"],
  se_tab_rates: ["Rates and services", "អត្រា និងសេវា"],
  se_tab_units: ["Parking setup", "ការរៀបចំចំណត"],
  se_tab_users: ["Users and sign-in", "អ្នកប្រើ និងការចូល"],
  se_tab_health: ["System health", "សុខភាពប្រព័ន្ធ"],
  // new: tabs not rebuilt yet keep the earlier forms.
  earlier: ["Earlier forms (English)", "ទម្រង់មុន (អង់គ្លេស)"],
  // V1-061 Fix 4 (owner bug list 29/10/2026): the tabs waited forever with no Property open.
  no_property: [
    "No Property is open yet. On the Business tab, open “Earlier forms (English)”, type the Property identifier and press “Load business configuration”. Then every tab fills in.",
    "មិនទាន់មានអគារបើកនៅឡើយទេ។ នៅផ្ទាំងអាជីវកម្ម សូមបើក “ទម្រង់មុន (អង់គ្លេស)” វាយលេខសម្គាល់អគារ ហើយចុច “Load business configuration”។ បន្ទាប់មក ផ្ទាំងទាំងអស់នឹងបង្ហាញព័ត៌មាន។",
  ],
  // new
  earlier_note: [
    "This tab is rebuilt in a later step. Until then the earlier forms below still work.",
    "ផ្ទាំងនេះនឹងរៀបចំឡើងវិញនៅជំហានក្រោយ។ រហូតដល់ពេលនោះ ទម្រង់មុនខាងក្រោមនៅតែប្រើបាន។",
  ],
  // new: the Users tab is rebuilt; role bundles are not in the mock-up.
  earlier_kept: [
    "Role bundles and the full list of access changes are still in the earlier forms below.",
    "កញ្ចប់តួនាទី និងបញ្ជីពេញនៃការប្តូរសិទ្ធិ នៅតែមាននៅក្នុងទម្រង់មុនខាងក្រោម។",
  ],
  // new: the Business tab is rebuilt; the earlier forms stay until the old screens go.
  earlier_same: [
    "The earlier forms below change the same things. They go when the old screens are removed.",
    "ទម្រង់មុនខាងក្រោម ប្តូររឿងដដែល។ វានឹងដកចេញ ពេលអេក្រង់ចាស់ត្រូវដកចេញ។",
  ],
  // new
  no_tab: [
    "Your account cannot open this tab.",
    "គណនីរបស់អ្នកមិនអាចបើកផ្ទាំងនេះបានទេ។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],

  se_health: ["System health", "សុខភាពប្រព័ន្ធ"],
  se_ok: ["Healthy", "ល្អ"],
  se_warn: ["Needs attention", "ត្រូវការការយកចិត្តទុកដាក់"],
  se_version: ["App version", "កំណែកម្មវិធី"],
  se_db: ["Database", "មូលដ្ឋានទិន្នន័យ"],
  se_migration: ["Migration", "ការធ្វើចំណាកស្រុក"],
  se_backup: ["Last backup", "បម្រុងទុកចុងក្រោយ"],
  se_last_bill: ["Last billing run", "ការចេញវិក្កយបត្រចុងក្រោយ"],
  se_last_exp: [
    "Last reservation expiry check",
    "ពិនិត្យផុតកំណត់ការកក់ចុងក្រោយ",
  ],
  se_health_n: [
    "Owner and Managers see this page. It is read-only; the engineer fixes problems outside the app.",
    "ម្ចាស់ និងអ្នកគ្រប់គ្រងឃើញទំព័រនេះ។ អានបានតែប៉ុណ្ណោះ។ វិស្វករជួសជុលបញ្ហានៅក្រៅកម្មវិធី។",
  ],
  // new
  db_ok: ["PostgreSQL · Healthy", "PostgreSQL · ល្អ"],
  // new
  db_down: ["PostgreSQL · Not answering", "PostgreSQL · មិនឆ្លើយតប"],
  // new
  db_none: ["Not set up", "មិនទាន់រៀបចំ"],
  // new
  offsite: ["Copy to another place", "ចម្លងទៅកន្លែងផ្សេង"],
  // new
  offsite_v: ["Daily {0} · Weekly {1}", "ប្រចាំថ្ងៃ {0} · ប្រចាំសប្តាហ៍ {1}"],
  // new
  restore: ["Last restore test", "តេស្តស្តារចុងក្រោយ"],
  // new
  alerts: ["Telegram alerts", "ការជូនដំណឹង Telegram"],
  // new
  alerts_on: ["On · last sent {0}", "បើក · ផ្ញើចុងក្រោយ {0}"],
  // new
  alerts_on_never: ["On · nothing sent yet", "បើក · មិនទាន់ផ្ញើ"],
  // new
  alerts_off: ["Not set up", "មិនទាន់រៀបចំ"],
  // new
  last_check: ["Last health check", "ការពិនិត្យសុខភាពចុងក្រោយ"],
  // new
  never: ["Not yet", "មិនទាន់"],
  // new
  failed_at: ["Failed {0}", "បរាជ័យ {0}"],
  // new
  ok_at: ["{0} · OK", "{0} · ល្អ"],
  // new
  warn_h: ["What needs attention", "អ្វីដែលត្រូវយកចិត្តទុកដាក់"],
  // new
  warn_lang: [
    "These notes come from the server in English.",
    "កំណត់ចំណាំទាំងនេះមកពីម៉ាស៊ីនមេជាភាសាអង់គ្លេស។",
  ],
  // new
  health_loading: ["Reading System health…", "កំពុងអានសុខភាពប្រព័ន្ធ…"],
  // new
  health_failed: [
    "System health could not be read just now. The app may still be working; try again.",
    "មិនអាចអានសុខភាពប្រព័ន្ធបានទេឥឡូវនេះ។ កម្មវិធីអាចនៅដំណើរការ សូមព្យាយាមម្តងទៀត។",
  ],
  // new
  checked_at: ["Read at {0}", "អាននៅ {0}"],

  cf_note: [
    "These lists fill the choices on New Parking and Update Parking. An item used by a Parking cannot be removed; rename it instead.",
    "បញ្ជីទាំងនេះបំពេញជម្រើសនៅលើចំណតថ្មី និងកែចំណត។ ធាតុដែលចំណតកំពុងប្រើ មិនអាចដកចេញបានទេ សូមប្តូរឈ្មោះវិញ។",
  ],
  cf_FLOOR: ["Floors", "ជាន់"],
  cf_UNIT_TYPE: ["Parking Types", "ប្រភេទចំណត"],
  cf_VIEW: ["Views", "ទេសភាព"],
  cf_KITCHEN: ["Kitchens", "ផ្ទះបាយ"],
  cf_ROOM_FEATURE: ["Room features", "លក្ខណៈចំណត"],
  cf_one_FLOOR: ["Floor", "ជាន់"],
  cf_one_UNIT_TYPE: ["Parking Type", "ប្រភេទចំណត"],
  cf_one_VIEW: ["View", "ទេសភាព"],
  cf_one_KITCHEN: ["Kitchen", "ផ្ទះបាយ"],
  cf_one_ROOM_FEATURE: ["Room feature", "លក្ខណៈចំណត"],
  cf_add: ["Add", "បន្ថែម"],
  cf_edit: ["Edit", "កែ"],
  cf_floor_no: ["Floor number", "លេខជាន់"],
  cf_en: ["Name in English", "ឈ្មោះជាភាសាអង់គ្លេស"],
  cf_kh: ["Name in Khmer", "ឈ្មោះជាភាសាខ្មែរ"],
  cf_e_floor: [
    "Enter a floor number from 0 to 99.",
    "សូមបញ្ចូលលេខជាន់ពី 0 ដល់ 99។",
  ],
  cf_e_dup: ['"{0}" is already in the list.', '"{0}" មាននៅក្នុងបញ្ជីរួចហើយ។'],
  cf_type_note: [
    "Rename keeps every Parking of this type. Add the new type to a move-out cleaning rate on the Rates and services tab.",
    "ការប្តូរឈ្មោះរក្សាចំណតទាំងអស់នៃប្រភេទនេះ។ សូមបន្ថែមប្រភេទថ្មីទៅអត្រាសម្អាតពេលចាកចេញ នៅផ្ទាំងអត្រា និងសេវា។",
  ],
  // Parking Step 5: no cleaning charge on Parking
  cf_type_note_parking: [
    "Rename keeps every Parking of this type.",
    "ការប្តូរឈ្មោះរក្សាចំណតទាំងអស់នៃប្រភេទនេះ។",
  ],
  cf_feat_note: [
    "Room features show as Yes or No on each Parking page.",
    "លក្ខណៈចំណតបង្ហាញជា មាន ឬ គ្មាន នៅលើទំព័រចំណតនីមួយៗ។",
  ],
  cf_saved: ["Saved.", "បានរក្សា។"],
  u_floor_n: ["Floor {0}", "ជាន់ទី {0}"],
  se_e_name: ["Enter a name.", "បញ្ចូលឈ្មោះ។"],
  set_n_unit1: ["1 Parking", "1 ចំណត"],
  set_n_units: ["{0} Parking", "{0} ចំណត"],
  set_none_units: ["No Parking yet", "មិនទាន់មានចំណត"],
  set_remove: ["Remove", "ដកចេញ"],
  set_removed: ["{0} removed.", "បានដក {0} ចេញ។"],
  set_remove_q: [
    "Remove {0}? This cannot be undone. Records made before keep it.",
    "ដក {0} ចេញ? មិនអាចត្រឡប់វិញបានទេ។ កំណត់ត្រាដែលធ្វើពីមុនរក្សាវាទុក។",
  ],
  save: ["Save", "រក្សាទុក"],
  required: ["Required", "ចាំបាច់"],
  cancel: ["Cancel", "បោះបង់"],
  // new: the Units could not be read, so only "in use" is known.
  in_use: ["Used by a Parking", "ចំណតកំពុងប្រើ"],
  // new
  units_loading: ["Reading the lists…", "កំពុងអានបញ្ជី…"],
  // new
  units_failed: [
    "The lists could not be read just now. Check the connection and try again.",
    "មិនអាចអានបញ្ជីបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  changed: [
    "Someone changed this list, or a Parking now uses the item. The lists were read again; check and try again.",
    "មាននរណាម្នាក់បានប្តូរបញ្ជីនេះ ឬចំណតមួយកំពុងប្រើធាតុនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  refused: [
    "The server did not accept this. Check the name and try again.",
    "ម៉ាស៊ីនមេមិនទទួលយកទេ។ សូមពិនិត្យឈ្មោះ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  unknown: [
    "The answer did not come back. The lists were read again; check before trying again.",
    "ចម្លើយមិនបានត្រឡប់មកវិញទេ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យមុននឹងព្យាយាមម្តងទៀត។",
  ],
  // new
  read_only: [
    "You can read these lists. Only the Owner or a user the Owner allows can change them.",
    "អ្នកអាចអានបញ្ជីទាំងនេះ។ មានតែម្ចាស់ ឬអ្នកប្រើដែលម្ចាស់អនុញ្ញាតទេ ដែលអាចប្តូរបាន។",
  ],

  // R7b-3 Users and sign-in
  se_users: ["Users", "អ្នកប្រើ"],
  se_user: ["Name", "ឈ្មោះ"],
  se_role: ["Role", "តួនាទី"],
  se_mfa: ["MFA", "MFA"],
  ua_col: ["Can change settings", "អាចប្តូរការកំណត់"],
  se_state: ["State", "ស្ថានភាព"],
  ur_col: ["Sign-in help", "ជំនួយការចូល"],
  se_active: ["Active", "សកម្ម"],
  se_disabled: ["Disabled", "បានបិទ"],
  se_mfa_off: ["Not needed", "មិនចាំបាច់"],
  // new: the server knows the account must use MFA, not whether it is set up yet.
  mfa_needed: ["Needed", "ត្រូវការ"],
  role_owner: ["Owner", "ម្ចាស់"],
  role_manager: ["Manager", "អ្នកគ្រប់គ្រង"],
  role_staff: ["Staff", "បុគ្គលិក"],
  // new: an account made before the three roles.
  role_other: ["Other", "ផ្សេងទៀត"],
  se_new_user: ["Add user", "បន្ថែមអ្នកប្រើ"],
  ua_btn: ["Settings access", "សិទ្ធិការកំណត់"],
  se_revoke: ["End all sessions", "បញ្ចប់វគ្គទាំងអស់"],
  se_revoke_q: [
    "Everyone except you is signed out now. They can sign in again.",
    "អ្នករាល់គ្នាលើកលែងតែអ្នក ត្រូវចេញពីប្រព័ន្ធឥឡូវ។ ពួកគេអាចចូលម្តងទៀតបាន។",
  ],
  se_revoke_done: [
    "Everyone else is signed out.",
    "អ្នកផ្សេងទាំងអស់បានចេញពីប្រព័ន្ធ។",
  ],
  // new
  revoke_some: [
    "Not everyone could be signed out. Try again.",
    "មិនអាចឲ្យអ្នកទាំងអស់ចេញពីប្រព័ន្ធបានទេ។ សូមព្យាយាមម្តងទៀត។",
  ],
  // new: replaces the mock-up's note, because only the Owner can open this tab.
  users_note: [
    "Only the Owner sees and changes this tab. Every change is kept in History.",
    "មានតែម្ចាស់ទេ ដែលឃើញ និងប្តូរផ្ទាំងនេះ។ ការប្តូរនីមួយៗរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  se_bundles: ["What each role can do", "តួនាទីនីមួយៗធ្វើអ្វីបាន"],
  se_cap: ["Work", "ការងារ"],
  cap_daily: [
    "Daily work: Payments, Invoices, readings, Parking, Customers, Reservations, Leases, move-out steps",
    "ការងារប្រចាំថ្ងៃ៖ ការបង់ប្រាក់ វិក្កយបត្រ អំណាន ចំណត អតិថិជន ការកក់ កិច្ចសន្យា ជំហានចាកចេញ",
  ],
  cap_drafts: [
    "Prepare drafts: Final Settlements, Refunds, corrections",
    "រៀបចំសេចក្តីព្រាង៖ ការទូទាត់ចុងក្រោយ ការសងវិញ ការកែ",
  ],
  cap_approve: [
    "Financial approval: void, adjust, late charges, deposit variances, sign and terminate Leases, confirm Settlements and Refunds",
    "ការអនុម័តហិរញ្ញវត្ថុ៖ លុបចោល កែតម្រូវ ថ្លៃពិន័យ ប្រាក់កក់ខុសគ្នា ចុះហត្ថលេខា និងបញ្ចប់កិច្ចសន្យា បញ្ជាក់ការទូទាត់ និងការសងវិញ",
  ],
  cap_reports: [
    "All reports, History and exports",
    "របាយការណ៍ទាំងអស់ ប្រវត្តិ និងការនាំចេញ",
  ],
  cap_ops: [
    "Operational reports only (no money totals)",
    "របាយការណ៍ប្រតិបត្តិការប៉ុណ្ណោះ (គ្មានសរុបលុយ)",
  ],
  cap_health: ["System health page", "ទំព័រសុខភាពប្រព័ន្ធ"],
  cap_settings: [
    "Business settings, users and roles",
    "ការកំណត់អាជីវកម្ម អ្នកប្រើ និងតួនាទី",
  ],
  ua_if: ["If the Owner allows", "បើម្ចាស់អនុញ្ញាត"],
  // new
  yes: ["Yes", "បាទ/ចាស"],
  // new
  no: ["No", "ទេ"],
  se_signin: ["Sign-in rules", "ច្បាប់ចូល"],
  se_signin_1: [
    "Local sign-in with name and password; no first Owner created from the web.",
    "ចូលក្នុងមូលដ្ឋានដោយឈ្មោះ និងពាក្យសម្ងាត់; គ្មានម្ចាស់ដំបូងបង្កើតពីវេប។",
  ],
  se_signin_2: [
    "Owner and Managers must use a second code (MFA app), with recovery codes kept safe.",
    "ម្ចាស់ និងអ្នកគ្រប់គ្រង ត្រូវប្រើកូដទីពីរ (កម្មវិធី MFA) ជាមួយកូដសង្គ្រោះរក្សាសុវត្ថិភាព។",
  ],
  se_signin_3: [
    "A session ends after 30 minutes without activity, and always after 24 hours.",
    "វគ្គបញ្ចប់បន្ទាប់ពី 30 នាទីគ្មានសកម្មភាព និងជានិច្ចបន្ទាប់ពី 24 ម៉ោង។",
  ],
  se_signin_5: [
    "After 3 wrong passwords the person waits 5 minutes. After 2 more, they wait 15 minutes, and again after every 2 more.",
    "បន្ទាប់ពីពាក្យសម្ងាត់ខុស ៣ ដង ត្រូវរង់ចាំ ៥ នាទី។ ខុស ២ ដងទៀត ត្រូវរង់ចាំ ១៥ នាទី ហើយម្តងទៀតរាល់ ២ ដងបន្ថែម។",
  ],
  se_signin_4: [
    "Disabling a user ends their sessions at once. Nothing is ever deleted.",
    "ការបិទអ្នកប្រើ បញ្ចប់វគ្គរបស់គេភ្លាម។ គ្មានអ្វីលុបទេ។",
  ],
  // Add user
  // new
  username: ["Username", "ឈ្មោះអ្នកប្រើ"],
  // new
  username_h: [
    "The person types this to sign in. It cannot be changed later.",
    "អ្នកនោះវាយឈ្មោះនេះដើម្បីចូល។ មិនអាចប្តូរនៅពេលក្រោយបានទេ។",
  ],
  // new: the server makes only Staff and Managers; there is one Owner.
  owner_one: [
    "There is one Owner. Add Staff or Managers here.",
    "មានម្ចាស់តែម្នាក់។ បន្ថែមបុគ្គលិក ឬអ្នកគ្រប់គ្រងនៅទីនេះ។",
  ],
  se_user_note: [
    "The new user sets a password at first sign-in. Owners and Managers must also set up the MFA app.",
    "អ្នកប្រើថ្មីកំណត់ពាក្យសម្ងាត់ពេលចូលលើកដំបូង។ ម្ចាស់ និងអ្នកគ្រប់គ្រងត្រូវរៀបចំកម្មវិធី MFA ផងដែរ។",
  ],
  // new
  e_username: ["Type a username.", "សូមវាយឈ្មោះអ្នកប្រើ។"],
  se_e_dup: ["{0} already exists.", "{0} មានរួចហើយ។"],
  se_user_saved: ["{0} added.", "បានបន្ថែម {0}។"],
  // One-time password
  ur_done_t: ["One-time password for {0}", "ពាក្យសម្ងាត់ប្រើម្តងសម្រាប់ {0}"],
  ur_done_s: [
    "Give it to {0} in person. Do not send it by chat. It works once, within 24 hours. They choose their own password when they sign in.",
    "ផ្តល់ឱ្យ {0} ដោយផ្ទាល់។ កុំផ្ញើតាមការជជែក។ ប្រើបានម្តង ក្នុងរយៈពេល ២៤ ម៉ោង។ គាត់ជ្រើសពាក្យសម្ងាត់ផ្ទាល់ខ្លួនពេលចូល។",
  ],
  // new
  otp_until: ["Works until {0}.", "ប្រើបានរហូតដល់ {0}។"],
  ur_done_once: [
    "The app shows this only now. If it is lost, reset again.",
    "កម្មវិធីបង្ហាញតែឥឡូវនេះ។ បើបាត់ សូមកំណត់ឡើងវិញម្តងទៀត។",
  ],
  ur_copy: ["Copy", "ចម្លង"],
  ur_copied: ["Copied.", "បានចម្លង។"],
  // new
  copy_failed: [
    "Could not copy. Write it down instead.",
    "មិនអាចចម្លងបានទេ។ សូមសរសេរវាទុកជំនួសវិញ។",
  ],
  ur_close: ["Done", "រួចរាល់"],
  // Reset
  ur_btn: ["Reset", "កំណត់ឡើងវិញ"],
  ur_t: ["Reset sign-in for {0}", "កំណត់ការចូលឡើងវិញសម្រាប់ {0}"],
  ur_what: ["What to reset", "អ្វីដែលត្រូវកំណត់ឡើងវិញ"],
  ur_pw: ["Password", "ពាក្យសម្ងាត់"],
  ur_pw_s: [
    "They forgot it. The app makes a one-time password for you to give them.",
    "គាត់ភ្លេច។ កម្មវិធីបង្កើតពាក្យសម្ងាត់ប្រើម្តង ឱ្យអ្នកផ្តល់ទៅគាត់។",
  ],
  ur_mfa: ["Two-step sign-in", "ការចូលពីរជំហាន"],
  ur_mfa_s: [
    "They lost or changed their phone. They set it up again at the next sign-in.",
    "គាត់បាត់ ឬប្តូរទូរស័ព្ទ។ គាត់រៀបចំម្តងទៀតពេលចូលលើកក្រោយ។",
  ],
  // new: the server's reset always replaces the password too (L4).
  ur_mfa_pw: [
    "The password is replaced too: give them the one-time password.",
    "ពាក្យសម្ងាត់ក៏ត្រូវប្តូរដែរ៖ សូមផ្តល់ពាក្យសម្ងាត់ប្រើម្តងទៅគាត់។",
  ],
  ur_reason: ["Reason", "មូលហេតុ"],
  ur_choose: ["Choose a reason", "ជ្រើសមូលហេតុ"],
  ur_r_forgot: ["Forgot password", "ភ្លេចពាក្យសម្ងាត់"],
  ur_r_phone: ["Lost or new phone", "បាត់ ឬប្តូរទូរស័ព្ទ"],
  ur_r_risk: [
    "Password may be known by someone else",
    "ពាក្យសម្ងាត់ប្រហែលជាអ្នកផ្សេងដឹង",
  ],
  ur_r_other: ["Other", "ផ្សេងទៀត"],
  ur_note: ["Note", "កំណត់ចំណាំ"],
  ur_note_ph: [
    "For example: asked at reception, 19/10 08:10",
    "ឧទាហរណ៍៖ បានសួរនៅកន្លែងទទួលភ្ញៀវ 19/10 08:10",
  ],
  ur_conseq: [
    "{0} is signed out everywhere at once. This is written to History.",
    "{0} ត្រូវចាកចេញពីគ្រប់កន្លែងភ្លាមៗ។ វាត្រូវកត់ក្នុងប្រវត្តិ។",
  ],
  ur_ok: ["Reset now", "កំណត់ឡើងវិញឥឡូវ"],
  ur_e_what: ["Choose what to reset.", "សូមជ្រើសអ្វីដែលត្រូវកំណត់ឡើងវិញ។"],
  ur_e_reason: ["Choose a reason.", "សូមជ្រើសមូលហេតុ។"],
  ur_e_note: ["Write what happened.", "សូមសរសេរអ្វីដែលបានកើតឡើង។"],
  // Disable (new: the mock-up names it only in the sign-in rules)
  dis_btn: ["Disable", "បិទ"],
  dis_t: ["Disable {0}", "បិទ {0}"],
  dis_q: [
    "{0} is signed out at once and can no longer sign in. Nothing is deleted. The app cannot turn the account on again.",
    "{0} ត្រូវចេញពីប្រព័ន្ធភ្លាម ហើយមិនអាចចូលបានទៀតទេ។ គ្មានអ្វីលុបទេ។ កម្មវិធីមិនអាចបើកគណនីនេះវិញបានទេ។",
  ],
  dis_done: ["{0} is disabled.", "បានបិទ {0}។"],
  // Settings access
  ua_title: ["Who can change settings", "អ្នកដែលអាចប្តូរការកំណត់"],
  ua_note: [
    "The Owner can always change settings. Tick the users you trust to change them too. Every change is kept in History.",
    "ម្ចាស់អាចប្តូរការកំណត់ជានិច្ច។ សូមធីកអ្នកប្រើដែលអ្នកទុកចិត្ត ឲ្យប្តូរបានដែរ។ ការប្តូរនីមួយៗរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  // new: the server keeps a reason with each change.
  ua_reason_h: [
    "Kept in History with each change.",
    "រក្សាទុកក្នុងប្រវត្តិ ជាមួយការប្តូរនីមួយៗ។",
  ],
  // new
  ua_e_reason: ["Write the reason.", "សូមសរសេរមូលហេតុ។"],
  // new
  ua_e_none: ["Nothing was changed.", "គ្មានអ្វីត្រូវបានប្តូរទេ។"],
  // new
  ua_e_code: [
    "{0}: a Staff account gets Settings access only after it has set up its sign-in code.",
    "{0}៖ គណនីបុគ្គលិកទទួលបានសិទ្ធិការកំណត់ លុះត្រាតែបានរៀបចំកូដចូលរួចហើយ។",
  ],
  // new
  ua_e_one: ["{0}: not changed.", "{0}៖ មិនបានប្តូរទេ។"],
  se_saved: ["Saved.", "បានរក្សាទុក។"],
  // Confirm it is you (new: the server asks for the password and code again after 15 minutes)
  ra_t: ["Confirm it is you", "បញ្ជាក់ថាជាអ្នក"],
  ra_s: [
    "This changes who may use the app. Type your password and the 6-digit code from your phone. The app asks again after 15 minutes.",
    "សកម្មភាពនេះប្តូរអ្នកដែលអាចប្រើកម្មវិធី។ សូមវាយពាក្យសម្ងាត់ និងលេខកូដ ៦ ខ្ទង់ពីទូរស័ព្ទរបស់អ្នក។ កម្មវិធីសួរម្តងទៀតបន្ទាប់ពី ១៥ នាទី។",
  ],
  ra_pw: ["Your password", "ពាក្យសម្ងាត់របស់អ្នក"],
  ra_code: ["6-digit code", "លេខកូដ ៦ ខ្ទង់"],
  ra_e_pw: ["Type your password.", "សូមវាយពាក្យសម្ងាត់។"],
  ra_e_code: [
    "Type the 6 digits from your phone.",
    "សូមវាយលេខ ៦ ខ្ទង់ពីទូរស័ព្ទ។",
  ],
  ra_bad: [
    "The password or code is not right, or you were signed out. Check both and try again.",
    "ពាក្យសម្ងាត់ ឬលេខកូដមិនត្រឹមត្រូវ ឬអ្នកបានចេញពីប្រព័ន្ធ។ សូមពិនិត្យទាំងពីរ ហើយព្យាយាមម្តងទៀត។",
  ],
  ra_wait: [
    "Too many tries. Wait {0} minutes, then try again.",
    "ព្យាយាមច្រើនដងពេក។ សូមរង់ចាំ {0} នាទី រួចព្យាយាមម្តងទៀត។",
  ],
  ra_down: [
    "The office computer did not answer. Try again.",
    "កុំព្យូទ័រការិយាល័យមិនបានឆ្លើយតបទេ។ សូមព្យាយាមម្តងទៀត។",
  ],
  ra_ok: ["Continue", "បន្ត"],
  // Users answers (new)
  users_loading: ["Reading the users…", "កំពុងអានអ្នកប្រើ…"],
  users_failed: [
    "The users could not be read just now. Check the connection and try again.",
    "មិនអាចអានអ្នកប្រើបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  users_changed: [
    "Someone changed this account. The list was read again; check and try again.",
    "មាននរណាម្នាក់បានប្តូរគណនីនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  users_refused: [
    "Not done. The server said:",
    "មិនបានធ្វើទេ។ ម៉ាស៊ីនមេនិយាយថា៖",
  ],
  users_unknown: [
    "The answer did not come back. The list was read again; check before trying again.",
    "ចម្លើយមិនបានត្រឡប់មកវិញទេ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យមុននឹងព្យាយាមម្តងទៀត។",
  ],
  // new: a disabled account shows no buttons.
  none: ["—", "—"],

  // R7b-4 Business
  se_prop: ["Property", "អចលនទ្រព្យ"],
  se_edit: ["Edit", "កែ"],
  se_prop_name: ["Property", "អចលនទ្រព្យ"],
  // new
  address: ["Address", "អាសយដ្ឋាន"],
  // new
  no_address: ["Not given", "មិនទាន់ផ្តល់"],
  se_units: ["Parking", "ចំណត"],
  se_tz: ["Time zone", "ល្វែងម៉ោង"],
  se_tz_n: [
    "Due dates, expiry and reading days use Phnom Penh time.",
    "ថ្ងៃកំណត់បង់ ផុតកំណត់ និងថ្ងៃអាន ប្រើម៉ោងភ្នំពេញ។",
  ],
  se_lang: ["Screen language", "ភាសាអេក្រង់"],
  se_lang_v: ["English and Khmer", "អង់គ្លេស និងខ្មែរ"],
  se_billing: ["Billing calendar", "ប្រតិទិនគិតថ្លៃ"],
  se_read_day: ["Meters read on the", "អាននាឡិកាស្ទង់នៅថ្ងៃទី"],
  se_issue_day: ["Invoices issued on the", "ចេញវិក្កយបត្រនៅថ្ងៃទី"],
  se_due_day: [
    "Rent and Utilities due on the",
    "ថ្លៃឈ្នួល និងទឹកភ្លើង កំណត់បង់ថ្ងៃទី",
  ],
  se_misc_due: ["Other Invoices due", "វិក្កយបត្រផ្សេងកំណត់បង់"],
  cal_misc_v: ["{0} days after issue", "{0} ថ្ងៃបន្ទាប់ពីចេញ"],
  // new
  day_n: ["{0}th", "{0}"],
  se_late: ["Late-payment charge", "ថ្លៃពិន័យបង់យឺត"],
  // new: DL-076 (the app adds it by itself), not the mock-up's older words.
  late_v: [
    "{0}% of the amount unpaid, added by the app on the day after the Due Date",
    "{0}% នៃចំនួនមិនទាន់បង់ កម្មវិធីបន្ថែមដោយខ្លួនឯង នៅថ្ងៃបន្ទាប់ពីថ្ងៃកំណត់បង់",
  ],
  // new
  misc_note: [
    "These days apply to every one-time Invoice, such as move-out charges.",
    "ចំនួនថ្ងៃនេះប្រើសម្រាប់វិក្កយបត្រម្តងៗទាំងអស់ ដូចជាថ្លៃពេលចាកចេញ។",
  ],
  se_res: ["Reservations", "ការកក់"],
  se_res_days: ["Initial expiry at most", "ផុតកំណត់ដំបូងយ៉ាងច្រើន"],
  rs_days_v: [
    "{0} days after the Reservation Date",
    "{0} ថ្ងៃបន្ទាប់ពីថ្ងៃកក់",
  ],
  se_res_ext: ["One extension of at most", "ពន្យារម្តងយ៉ាងច្រើន"],
  rs_ext_v: ["{0} days, approved by a Manager", "{0} ថ្ងៃ អ្នកគ្រប់គ្រងអនុម័ត"],
  se_res_dep: ["Suggested deposit", "ប្រាក់កក់ណែនាំ"],
  rs_dep_v: [
    "{0}% of the agreed monthly Rent",
    "{0}% នៃថ្លៃជួលប្រចាំខែដែលបានព្រមព្រៀង",
  ],
  se_fixed: ["Set by the business rules", "កំណត់ដោយច្បាប់អាជីវកម្ម"],
  // new
  fixed_note: [
    "These follow the business rules for now. Changing them here comes in a later step.",
    "ទាំងនេះធ្វើតាមច្បាប់អាជីវកម្មសិន។ ការប្តូរនៅទីនេះនឹងមកក្នុងជំហានក្រោយ។",
  ],
  se_methods: ["Payment Methods", "វិធីបង់ប្រាក់"],
  pm_add: ["Add a method", "បន្ថែមវិធី"],
  pm_edit: ["Edit method", "កែវិធី"],
  pm_off: ["Turned off", "បានបិទ"],
  pm_note: [
    "A method used on Receipts is never deleted. Turn it off instead; old Receipts keep it.",
    "វិធីដែលប្រើនៅលើបង្កាន់ដៃ មិនត្រូវលុបទេ។ សូមបិទវាជំនួសវិញ; បង្កាន់ដៃចាស់រក្សាវាដដែល។",
  ],
  pm_name: ["Method name in English", "ឈ្មោះវិធីជាភាសាអង់គ្លេស"],
  pm_on: [
    "Staff can use it on new Receipts",
    "បុគ្គលិកអាចប្រើវានៅលើបង្កាន់ដៃថ្មី",
  ],
  pm_e_last: [
    "Keep at least one method turned on.",
    "ត្រូវបើកយ៉ាងហោចណាស់មួយវិធី។",
  ],
  sv_saved: ["{0} saved.", "បានរក្សា {0}។"],
  se_fx: ["Riel exchange rate", "អត្រាប្តូរប្រាក់រៀល"],
  // new
  fx_last: ["{0} ៛ per $1", "{0} ៛ ក្នុង $1"],
  // new
  fx_auto: ["ABA rate, {0}.", "អត្រា ABA {0}។"],
  // new
  fx_hand_v: ["Entered by hand, {0}.", "បញ្ចូលដោយដៃ {0}។"],
  // new
  fx_none: ["No riel payment yet.", "មិនទាន់មានការបង់ជារៀលទេ។"],
  // new
  fx_note: [
    "The rate is taken when a payment in riel is received: ABA Sell rate plus 0.5%, rounded up to the next 1 ៛.",
    "អត្រាត្រូវយកពេលទទួលការបង់ជារៀល៖ អត្រាលក់ ABA បូក 0.5% បង្គត់ឡើងទៅ 1 ៛ បន្ទាប់។",
  ],
  // new
  fx_cannot: ["The rate could not be read.", "មិនអាចអានអត្រាបានទេ។"],
  se_numbers: ["Numbers", "លេខ"],
  se_inv_no: ["Invoice numbers", "លេខវិក្កយបត្រ"],
  se_rcp_no: ["Receipt numbers", "លេខបង្កាន់ដៃ"],
  // new
  se_rfd_no: ["Refund numbers", "លេខការសងប្រាក់"],
  // new: the next number is not read from the server yet.
  no_v2: [
    "{0} + year + running number, for example {1}",
    "{0} + ឆ្នាំ + លេខរត់ ឧទាហរណ៍ {1}",
  ],
  // new
  days_n: ["Days after issue", "ចំនួនថ្ងៃបន្ទាប់ពីចេញ"],
  // new
  days_h: [
    "From 1 to 90. Invoices already issued keep their Due Date.",
    "ពី 1 ដល់ 90។ វិក្កយបត្រដែលចេញរួច រក្សាថ្ងៃកំណត់បង់ដដែល។",
  ],
  // new
  e_days: ["Enter a number from 1 to 90.", "សូមបញ្ចូលលេខពី 1 ដល់ 90។"],
  // new
  biz_loading: ["Reading the business settings…", "កំពុងអានការកំណត់អាជីវកម្ម…"],
  // new
  biz_failed: [
    "The business settings could not be read just now. Check the connection and try again.",
    "មិនអាចអានការកំណត់អាជីវកម្មបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  biz_changed: [
    "Someone changed these settings. They were read again; check and try again.",
    "មាននរណាម្នាក់បានប្តូរការកំណត់ទាំងនេះ។ បានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  // V1-058 R7b-5: Rates and services.
  earlier_rates: [
    "Confirming the riel exchange rate is still in the earlier forms below. They go when the old screens are removed.",
    "ការបញ្ជាក់អត្រាប្តូរប្រាក់រៀល នៅតែមាននៅក្នុងទម្រង់មុនខាងក្រោម។ វានឹងដកចេញ ពេលអេក្រង់ចាស់ត្រូវដកចេញ។",
  ],
  se_util: ["Utility Rates", "អត្រាទឹកភ្លើង"],
  se_util_add: ["Schedule a new Rate", "កំណត់អត្រាថ្មី"],
  se_util_n: [
    "Effective-dated. A new Rate starts on a reading day after notice; readings before it keep the old Rate.",
    "មានកាលបរិច្ឆេទប្រសិទ្ធភាព។ អត្រាថ្មីចាប់ផ្តើមនៅថ្ងៃអាន បន្ទាប់ពីជូនដំណឹង; អំណានមុនរក្សាអត្រាចាស់។",
  ],
  ro_kind: ["Kind", "ប្រភេទ"],
  ro_rate: ["Rate", "អត្រា"],
  ro_since: ["Since", "ចាប់ពី"],
  ro_until: ["Until", "ដល់"],
  // new: the server keeps when and how the tenants were told.
  ro_told: ["Tenants told", "ជូនដំណឹងអ្នកជួល"],
  k_EL: ["Electricity", "អគ្គិសនី"],
  k_WA: ["Water", "ទឹក"],
  se_sched: ["Starts later", "ចាប់ផ្តើមពេលក្រោយ"],
  se_util_per: ["Rate per kWh or m³", "អត្រាក្នុង kWh ឬ m³"],
  se_starts: ["Starts on", "ចាប់ផ្តើមនៅ"],
  se_util_day_help: [
    "A reading day (the 24th) after today.",
    "ថ្ងៃអាន (ថ្ងៃទី 24) បន្ទាប់ពីថ្ងៃនេះ។",
  ],
  se_e_read: [
    "Enter a 24th after today, like 24/11/2026.",
    "បញ្ចូលថ្ងៃទី 24 បន្ទាប់ពីថ្ងៃនេះ ដូចជា 24/11/2026។",
  ],
  se_e_same: [
    "A rate already starts on that day.",
    "មានអត្រាចាប់ផ្តើមនៅថ្ងៃនោះរួចហើយ។",
  ],
  // new
  told_on: ["Tenants told on", "ថ្ងៃជូនដំណឹងអ្នកជួល"],
  // new
  told_h: [
    "Before the start day, and not after today.",
    "មុនថ្ងៃចាប់ផ្តើម ហើយមិនក្រោយថ្ងៃនេះ។",
  ],
  // new
  e_told: [
    "Enter a day before the start day and not after today.",
    "បញ្ចូលថ្ងៃមុនថ្ងៃចាប់ផ្តើម ហើយមិនក្រោយថ្ងៃនេះ។",
  ],
  // new
  told_how: ["How the tenants were told", "របៀបជូនដំណឹងអ្នកជួល"],
  // new
  told_how_h: [
    "For example: a letter under each door, and the Telegram group.",
    "ឧទាហរណ៍៖ លិខិតដាក់ក្រោមទ្វារនីមួយៗ និងក្រុម Telegram។",
  ],
  // new
  e_told_how: [
    "Write how the tenants were told.",
    "សូមសរសេររបៀបជូនដំណឹងអ្នកជួល។",
  ],
  // new
  e_util_rate: [
    "Enter the rate in dollars, for example 0.25.",
    "សូមបញ្ចូលអត្រាជាដុល្លារ ឧទាហរណ៍ 0.25។",
  ],
  err_amount: [
    "Enter the amount in dollars and cents, for example 353.00.",
    "សូមបញ្ចូលចំនួនជាដុល្លារ និងសេន ឧទាហរណ៍ 353.00។",
  ],
  se_util_saved: ["New {0} Rate from {1}.", "អត្រា{0}ថ្មី ចាប់ពី {1}។"],
  se_svc: ["Services", "សេវា"],
  se_svc_n: [
    "Billed in advance on the Rent Invoice. Each Lease ticks its Services on the New Lease form. A new rate starts on the first day of a month and never changes Invoices already issued.",
    "គិតថ្លៃជាមុននៅលើវិក្កយបត្រថ្លៃឈ្នួល។ កិច្ចសន្យានីមួយៗធីកសេវារបស់ខ្លួននៅលើទម្រង់កិច្ចសន្យាថ្មី។ អត្រាថ្មីចាប់ផ្តើមនៅថ្ងៃទីមួយនៃខែ ហើយមិនប្តូរវិក្កយបត្រដែលចេញរួចទេ។",
  ],
  se_svc_name: ["Service", "សេវា"],
  sv_rate_now: ["Monthly rate now", "អត្រាប្រចាំខែឥឡូវ"],
  sv_next: ["Next change", "ការប្តូរបន្ទាប់"],
  sv_hist: ["Rate history", "ប្រវត្តិអត្រា"],
  se_svc_rate_h: ["Monthly rate", "អត្រាប្រចាំខែ"],
  // new: the server keeps a Service's name; only a new rate is added here.
  sv_new: ["New rate", "អត្រាថ្មី"],
  set_from_help: [
    "The first day of a month after today.",
    "ថ្ងៃទីមួយនៃខែ បន្ទាប់ពីថ្ងៃនេះ។",
  ],
  se_e_first: [
    "Enter the first day of a month after today, like 01/12/2026.",
    "បញ្ចូលថ្ងៃទីមួយនៃខែ បន្ទាប់ពីថ្ងៃនេះ ដូចជា 01/12/2026។",
  ],
  sv_rate_h: [
    "The old rate stays on Invoices already issued.",
    "អត្រាចាស់នៅលើវិក្កយបត្រដែលចេញរួច។",
  ],
  se_svc_not_yet: ["starts {0}", "ចាប់ផ្តើម {0}"],
  // new
  sv_none: ["No Services yet.", "មិនទាន់មានសេវា។"],
  // new
  util_none: ["No Utility Rates yet.", "មិនទាន់មានអត្រាទឹកភ្លើង។"],
  // new (R7b-6b)
  sv_add: ["Add a Service", "បន្ថែមសេវា"],
  sv_type: ["Type", "ប្រភេទ"],
  sv_no_type: ["No type", "គ្មានប្រភេទ"],
  sv_leases: ["Leases using it", "កិច្ចសន្យាដែលប្រើ"],
  sv_name_note: [
    "A new name shows only on new Invoices. To change the amount, use New rate.",
    "ឈ្មោះថ្មីបង្ហាញតែលើវិក្កយបត្រថ្មីប៉ុណ្ណោះ។ ដើម្បីប្តូរចំនួនទឹកប្រាក់ សូមប្រើ អត្រាថ្មី។",
  ],
  sv_first_h: [
    "The first rate. It starts on the first day of a month.",
    "អត្រាដំបូង។ វាចាប់ផ្តើមនៅថ្ងៃទីមួយនៃខែ។",
  ],
  sv_added: ["{0} added.", "បានបន្ថែម {0}។"],
  sv_changed: ["{0} saved.", "បានរក្សាទុក {0}។"],
  sv_read_failed: [
    "The Service names and types could not be read just now, so they cannot be changed. The rates still show.",
    "មិនអាចអានឈ្មោះ និងប្រភេទសេវាបានទេឥឡូវនេះ ដូច្នេះមិនអាចប្តូរបានទេ។ អត្រានៅតែបង្ហាញ។",
  ],
  st_title: ["Service types", "ប្រភេទសេវា"],
  actions: ["Actions", "សកម្មភាព"],
  e_first_now: [
    "Enter the first day of this month or a later month, like 01/12/2026.",
    "បញ្ចូលថ្ងៃទីមួយនៃខែនេះ ឬខែក្រោយ ដូចជា 01/12/2026។",
  ],
  st_add: ["Add a Service type", "បន្ថែមប្រភេទសេវា"],
  st_rule: ["Per Lease", "ក្នុងមួយកិច្ចសន្យា"],
  st_one: ["Only one per Lease", "តែមួយក្នុងមួយកិច្ចសន្យា"],
  st_many: ["One or more per Lease", "មួយ ឬច្រើនក្នុងមួយកិច្ចសន្យា"],
  st_count: ["Services", "សេវា"],
  st_none: ["No Service types yet.", "មិនទាន់មានប្រភេទសេវា។"],
  st_used: ["Has {0} Services", "មានសេវា {0}"],
  st_used1: ["Has 1 Service", "មានសេវា 1"],
  st_note: [
    "The New Lease form groups Services by type: an Only one type shows a choice of one, a One or more type shows tick boxes. Changing a Service's type, or a type to Only one, is refused while a Lease holds two Services of that type.",
    "ទម្រង់កិច្ចសន្យាថ្មីដាក់សេវាជាក្រុមតាមប្រភេទ៖ ប្រភេទតែមួយបង្ហាញជម្រើសមួយ ប្រភេទមួយ ឬច្រើនបង្ហាញប្រអប់ធីក។ ការប្តូរប្រភេទសេវា ឬប្តូរប្រភេទទៅជាតែមួយ ត្រូវបានបដិសេធ ខណៈកិច្ចសន្យាមួយមានសេវាពីរនៃប្រភេទនោះ។",
  ],
  e_name: [
    "Enter a name of 1 to 100 letters.",
    "បញ្ចូលឈ្មោះពី 1 ដល់ 100 តួអក្សរ។",
  ],
  f_lease_two: [
    "A Lease holds two Services of this type, so this change is refused. End one of them on that Lease first.",
    "កិច្ចសន្យាមួយមានសេវាពីរនៃប្រភេទនេះ ដូច្នេះការប្តូរនេះត្រូវបានបដិសេធ។ សូមបញ្ចប់សេវាមួយនៅលើកិច្ចសន្យានោះជាមុនសិន។",
  ],
  f_type_has: [
    "This Service type has Services, so it cannot be removed. Move them to another type first.",
    "ប្រភេទសេវានេះមានសេវា ដូច្នេះមិនអាចដកចេញបានទេ។ សូមផ្លាស់សេវាទាំងនោះទៅប្រភេទផ្សេងជាមុនសិន។",
  ],
  f_out_of_date: [
    "Someone changed this first. The list was read again; check and try again.",
    "នរណាម្នាក់បានប្តូរវាមុន។ បញ្ជីត្រូវបានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
  f_gone: [
    "This is no longer in the list; someone may have removed it. The list was read again.",
    "វាលែងមាននៅក្នុងបញ្ជីទៀតហើយ ប្រហែលជានរណាម្នាក់បានដកវាចេញ។ បញ្ជីត្រូវបានអានម្តងទៀត។",
  ],
  f_id_reused: [
    "This was already saved, with the values sent first. It is in the list now; change it there if needed.",
    "វាត្រូវបានរក្សាទុករួចហើយ ដោយតម្លៃដែលបានផ្ញើលើកដំបូង។ វានៅក្នុងបញ្ជីឥឡូវនេះ សូមប្តូរនៅទីនោះ បើត្រូវការ។",
  ],
  // V1-058 R7b-6d: the move-out cleaning rates by Unit Type.
  cl_title: ["Move-out cleaning rates", "អត្រាសម្អាតពេលចាកចេញ"],
  cl_add: ["Add a cleaning rate", "បន្ថែមអត្រាសម្អាត"],
  cl_name: ["Name", "ឈ្មោះ"],
  cl_types: ["Parking Types", "ប្រភេទចំណត"],
  cl_rate: ["Rate", "អត្រា"],
  cl_none: ["No cleaning rates yet.", "មិនទាន់មានអត្រាសម្អាត។"],
  cl_missing: [
    "No cleaning rate yet: {0}. Tick them in a cleaning rate.",
    "មិនទាន់មានអត្រាសម្អាត៖ {0}។ សូមធីកពួកវានៅក្នុងអត្រាសម្អាតមួយ។",
  ],
  cl_needs: [
    "{0} has Parking and needs a cleaning rate. Put it in another rate first.",
    "{0} មានចំណត ហើយត្រូវការអត្រាសម្អាត។ សូមដាក់វាក្នុងអត្រាផ្សេងជាមុនសិន។",
  ],
  cl_moves: [
    "Now in {0}; ticking moves it here.",
    "ឥឡូវនៅក្នុង {0}។ ការធីកនឹងផ្លាស់វាមកទីនេះ។",
  ],
  cl_note: [
    "A move-out has a cleaning charge at the rate of the Parking's type. A new amount applies to every Parking of its types from now on; charges already made keep theirs.",
    "ការចាកចេញមានថ្លៃសម្អាត តាមអត្រានៃប្រភេទចំណត។ ចំនួនថ្មីអនុវត្តចំពោះចំណតទាំងអស់នៃប្រភេទរបស់វា ចាប់ពីពេលនេះតទៅ ថ្លៃដែលបានធ្វើរួចរក្សាចំនួនដើម។",
  ],
  cl_chip: ["No cleaning rate", "គ្មានអត្រាសម្អាត"],
  cl_read_failed: [
    "The cleaning rates could not be read just now. Check the connection and try again.",
    "មិនអាចអានអត្រាសម្អាតបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  f_needs_rate: [
    "A Parking Type that has Parking needs a cleaning rate. Put it in another rate first. The list was read again.",
    "ប្រភេទចំណតដែលមានចំណត ត្រូវការអត្រាសម្អាត។ សូមដាក់វាក្នុងអត្រាផ្សេងជាមុនសិន។ បញ្ជីត្រូវបានអានម្តងទៀត។",
  ],
  // new
  note_l: ["Note", "កំណត់ចំណាំ"],
  optional: ["Optional", "មិនចាំបាច់"],
  // new
  rates_loading: ["Reading the rates…", "កំពុងអានអត្រា…"],
  // new
  rates_failed: [
    "The rates could not be read just now. Check the connection and try again.",
    "មិនអាចអានអត្រាបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new: the same key makes a second Save safe.
  rates_unknown: [
    "The answer did not come back, so it may be saved already. Press Save again without changing anything: it is not saved twice.",
    "ចម្លើយមិនបានត្រឡប់មកវិញទេ ដូច្នេះវាប្រហែលជាបានរក្សាទុករួចហើយ។ ចុចរក្សាទុកម្តងទៀត ដោយមិនប្តូរអ្វីទាំងអស់៖ វាមិនរក្សាទុកពីរដងទេ។",
  ],
  // new
  rates_refused: [
    "The server did not accept this. Check the values and try again.",
    "ម៉ាស៊ីនមេមិនទទួលយកទេ។ សូមពិនិត្យតម្លៃ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  rates_changed: [
    "A rate already starts on that day, or someone else changed the rates. They were read again; check and try again.",
    "មានអត្រាចាប់ផ្តើមនៅថ្ងៃនោះរួចហើយ ឬនរណាម្នាក់បានប្តូរអត្រា។ បានអានម្តងទៀត សូមពិនិត្យ ហើយព្យាយាមម្តងទៀត។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type SettingsTextKey = keyof typeof TEXT;

/** The words for `key`, with {0}, {1} … filled in. */
export function sst(
  language: Language,
  key: SettingsTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "km" ? 1 : 0];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}
