// Login sub-slice L6: the sign-in screens' text in English and Khmer, from the owner's mock-up
// (i18n7.js) with the changes of Q-2026-10-24-187. Keys marked "new" are not in the mock-up;
// their Khmer needs the native check before the app is used.

export type Language = "en" | "km";

const text = {
  au_app: ["Residence Management", "Residence Management"],
  au_where: [
    "CHETANA Residence · office computer",
    "CHETANA Residence · កុំព្យូទ័រការិយាល័យ",
  ],
  au_fact1: [
    "Each person signs in with their own username.",
    "ម្នាក់ៗចូលដោយឈ្មោះអ្នកប្រើផ្ទាល់ខ្លួន។",
  ],
  // Changed: staff who can change settings use the code too (DL-081).
  au_fact2: [
    "Owner, Managers and staff who can change settings also type a code from their phone.",
    "ម្ចាស់ អ្នកគ្រប់គ្រង និងបុគ្គលិកដែលអាចប្តូរការកំណត់ វាយលេខកូដពីទូរស័ព្ទបន្ថែម។",
  ],
  au_fact3: [
    "The app signs you out after 30 minutes without use.",
    "កម្មវិធីចាកចេញដោយខ្លួនឯង ក្រោយ ៣០ នាទីមិនប្រើ។",
  ],
  au_lang: ["Language ភាសា", "Language ភាសា"],
  au_signin: ["Sign in", "ចូលប្រព័ន្ធ"],
  au_signin_s: [
    "Use the username the Owner gave you.",
    "ប្រើឈ្មោះអ្នកប្រើដែលម្ចាស់បានផ្តល់ឱ្យ។",
  ],
  au_user: ["Username", "ឈ្មោះអ្នកប្រើ"],
  au_pw: ["Password", "ពាក្យសម្ងាត់"],
  au_show: ["Show", "បង្ហាញ"],
  au_hide: ["Hide", "លាក់"],
  au_show_l: ["Show password", "បង្ហាញពាក្យសម្ងាត់"],
  au_hide_l: ["Hide password", "លាក់ពាក្យសម្ងាត់"],
  au_forgot: ["Forgot your password?", "ភ្លេចពាក្យសម្ងាត់?"],
  au_e_user: ["Type your username.", "សូមវាយឈ្មោះអ្នកប្រើ។"],
  au_e_pw: ["Type your password.", "សូមវាយពាក្យសម្ងាត់។"],
  au_e_wrong: [
    "The username or password is not right. Check both and try again.",
    "ឈ្មោះអ្នកប្រើ ឬពាក្យសម្ងាត់មិនត្រឹមត្រូវ។ សូមពិនិត្យទាំងពីរ ហើយសាកម្តងទៀត។",
  ],
  au_signed_out: ["You are signed out.", "អ្នកបានចាកចេញហើយ។"],
  au_code_t: ["Two-step sign-in", "ការចូលពីរជំហាន"],
  au_code_s: [
    "Open the authenticator app on your phone and type the 6-digit code for CHETANA.",
    "បើកកម្មវិធីផ្ទៀងផ្ទាត់ក្នុងទូរស័ព្ទ ហើយវាយលេខកូដ ៦ ខ្ទង់សម្រាប់ CHETANA។",
  ],
  au_code: ["6-digit code", "លេខកូដ ៦ ខ្ទង់"],
  au_code_h: [
    "The code changes every 30 seconds.",
    "លេខកូដប្តូររៀងរាល់ ៣០ វិនាទី។",
  ],
  au_e_code: [
    "Type the 6 digits from your phone.",
    "សូមវាយលេខ ៦ ខ្ទង់ពីទូរស័ព្ទ។",
  ],
  au_e_code_bad: [
    "That code is not right. Type the newest code from your phone.",
    "លេខកូដនោះមិនត្រឹមត្រូវ។ សូមវាយលេខកូដថ្មីបំផុតពីទូរស័ព្ទ។",
  ],
  au_use_rc: [
    "Lost your phone? Use a recovery code",
    "បាត់ទូរស័ព្ទ? ប្រើលេខកូដសង្គ្រោះ",
  ],
  au_use_app: ["Use the code from my phone", "ប្រើលេខកូដពីទូរស័ព្ទខ្ញុំ"],
  au_rc: ["Recovery code", "លេខកូដសង្គ្រោះ"],
  au_rc_h: [
    "One of the 10 codes you wrote down, like 7KQ4-M2XD. Each code works once.",
    "លេខកូដមួយក្នុងចំណោម ១០ ដែលអ្នកបានកត់ទុក ដូចជា 7KQ4-M2XD។ លេខកូដនីមួយៗប្រើបានតែម្តង។",
  ],
  au_e_rc: [
    "Type a recovery code, like 7KQ4-M2XD.",
    "សូមវាយលេខកូដសង្គ្រោះ ដូចជា 7KQ4-M2XD។",
  ],
  au_e_rc_bad: [
    "That recovery code does not work. It may be used already.",
    "លេខកូដសង្គ្រោះនោះមិនដំណើរការ។ វាប្រហែលជាត្រូវបានប្រើរួចហើយ។",
  ],
  au_verify: ["Continue", "បន្ត"],
  au_back_signin: ["Back to sign in", "ត្រឡប់ទៅចូលប្រព័ន្ធ"],
  // Changed: the server does not say how many codes are left, and a session signed in with a
  // recovery code cannot make new codes (API-098; L6 review round 1).
  au_rc_used: [
    "Recovery code used. If your phone is lost, ask the Owner to reset your two-step sign-in. Make new recovery codes after you sign in with your phone again.",
    "បានប្រើលេខកូដសង្គ្រោះ។ បើបាត់ទូរស័ព្ទ សូមសុំម្ចាស់ឱ្យកំណត់ការចូលពីរជំហានឡើងវិញ។ សូមបង្កើតលេខកូដសង្គ្រោះថ្មី បន្ទាប់ពីចូលដោយទូរស័ព្ទម្តងទៀត។",
  ],
  au_fg_t: ["Forgot your password?", "ភ្លេចពាក្យសម្ងាត់?"],
  au_fg_s: [
    "The app never sends passwords by email, SMS or Telegram. A new password is made in person.",
    "កម្មវិធីមិនដែលផ្ញើពាក្យសម្ងាត់តាមអ៊ីមែល SMS ឬ Telegram ទេ។ ពាក្យសម្ងាត់ថ្មីត្រូវធ្វើដោយផ្ទាល់។",
  ],
  au_fg_staff: ["Staff and Managers", "បុគ្គលិក និងអ្នកគ្រប់គ្រង"],
  au_fg_staff_s: [
    "Ask the Owner. The Owner resets your password and gives you a one-time password in person. You choose your own new password when you sign in with it.",
    "សូមសួរម្ចាស់។ ម្ចាស់កំណត់ពាក្យសម្ងាត់ឡើងវិញ ហើយផ្តល់ពាក្យសម្ងាត់ប្រើម្តងឱ្យអ្នកដោយផ្ទាល់។ អ្នកជ្រើសពាក្យសម្ងាត់ថ្មីខ្លួនឯង ពេលចូលដោយវា។",
  ],
  au_fg_owner: ["Owner", "ម្ចាស់"],
  // Changed: no reset with a recovery code (the Owner's reset is the emergency procedure).
  au_fg_owner_s: [
    "Forgot your password? Only the server emergency procedure can help. It is done on the office computer itself, by the person who set the app up.",
    "ភ្លេចពាក្យសម្ងាត់? មានតែនីតិវិធីបន្ទាន់លើម៉ាស៊ីនមេប៉ុណ្ណោះ។ វាធ្វើនៅលើកុំព្យូទ័រការិយាល័យផ្ទាល់ ដោយអ្នកដែលបានដំឡើងកម្មវិធី។",
  ],
  // New.
  au_fg_phone: [
    "Lost only your phone? Sign in with your password, then use a recovery code.",
    "បាត់តែទូរស័ព្ទ? សូមចូលដោយពាក្យសម្ងាត់ រួចប្រើលេខកូដសង្គ្រោះ។",
  ],
  au_np_t: ["Choose a new password", "ជ្រើសពាក្យសម្ងាត់ថ្មី"],
  au_np_temp: [
    "You signed in with a one-time password. Choose your own password now.",
    "អ្នកបានចូលដោយពាក្យសម្ងាត់ប្រើម្តង។ សូមជ្រើសពាក្យសម្ងាត់ផ្ទាល់ខ្លួនឥឡូវ។",
  ],
  au_new: ["New password", "ពាក្យសម្ងាត់ថ្មី"],
  au_new2: ["Type the new password again", "វាយពាក្យសម្ងាត់ថ្មីម្តងទៀត"],
  au_np_h: [
    "Use a short sentence you can remember, like “my blue door opens at seven”. Spaces are fine. A password manager is fine.",
    "ប្រើប្រយោគខ្លីដែលអ្នកចាំបាន ដូចជា “my blue door opens at seven”។ ដកឃ្លាបាន។ កម្មវិធីរក្សាពាក្យសម្ងាត់ក៏បាន។",
  ],
  au_r_len: ["At least 15 characters", "យ៉ាងតិច ១៥ តួអក្សរ"],
  au_r_now: ["now {0}", "ឥឡូវ {0}"],
  au_r_max: ["No more than 128 characters", "មិនលើស ១២៨ តួអក្សរ"],
  au_r_common: [
    "Not a common or easy-to-guess password",
    "មិនមែនពាក្យសម្ងាត់ធម្មតា ឬងាយទាយ",
  ],
  au_r_common_h: ["Checked when you save", "ពិនិត្យពេលរក្សាទុក"],
  au_r_same: ["Both boxes match", "ប្រអប់ទាំងពីរដូចគ្នា"],
  au_e_short: ["Use at least 15 characters.", "សូមប្រើយ៉ាងតិច ១៥ តួអក្សរ។"],
  au_e_long: ["Use no more than 128 characters.", "សូមប្រើមិនលើស ១២៨ តួអក្សរ។"],
  au_e_common: [
    "This password is too common or too easy to guess. Choose another.",
    "ពាក្យសម្ងាត់នេះធម្មតាពេក ឬងាយទាយពេក។ សូមជ្រើសផ្សេង។",
  ],
  au_e_same: [
    "The two new passwords are not the same.",
    "ពាក្យសម្ងាត់ថ្មីទាំងពីរមិនដូចគ្នា។",
  ],
  au_np_save: ["Save new password", "រក្សាទុកពាក្យសម្ងាត់ថ្មី"],
  au_np_done: [
    "Password changed. You are signed out on every other computer.",
    "បានប្តូរពាក្យសម្ងាត់។ អ្នកត្រូវបានចាកចេញពីកុំព្យូទ័រផ្សេងទាំងអស់។",
  ],
  // New: the change may have been saved before a later step failed (L4 review round 1).
  au_e_np_unknown: [
    "The password change did not finish. Sign in with your new password. If it is not accepted, sign in with your one-time password.",
    "ការប្តូរពាក្យសម្ងាត់មិនទាន់ចប់។ សូមចូលដោយពាក្យសម្ងាត់ថ្មី។ បើមិនត្រូវ សូមចូលដោយពាក្យសម្ងាត់ប្រើម្តង។",
  ],
  au_su_t: ["Set up two-step sign-in", "រៀបចំការចូលពីរជំហាន"],
  // Changed: everyone who sees this screen must do it (staff with Settings access too).
  au_su_s: [
    "You must do this once before using the app. It takes about two minutes.",
    "អ្នកត្រូវធ្វើម្តងមុនប្រើកម្មវិធី។ ចំណាយប្រហែលពីរនាទី។",
  ],
  au_su_1: [
    "Install an authenticator app on your phone, such as Google Authenticator or Microsoft Authenticator.",
    "ដំឡើងកម្មវិធីផ្ទៀងផ្ទាត់ក្នុងទូរស័ព្ទ ដូចជា Google Authenticator ឬ Microsoft Authenticator។",
  ],
  au_su_2: [
    "In the app, add an account and scan this code.",
    "ក្នុងកម្មវិធី បន្ថែមគណនី ហើយស្កេនកូដនេះ។",
  ],
  au_su_qr: [
    "QR code for your authenticator app",
    "កូដ QR សម្រាប់កម្មវិធីផ្ទៀងផ្ទាត់",
  ],
  au_su_key: [
    "Cannot scan? Type this key instead:",
    "ស្កេនមិនបាន? វាយលេខសោនេះជំនួស៖",
  ],
  au_su_3: [
    "Type the 6-digit code the app shows.",
    "វាយលេខកូដ ៦ ខ្ទង់ដែលកម្មវិធីបង្ហាញ។",
  ],
  au_rcs_t: ["Your recovery codes", "លេខកូដសង្គ្រោះរបស់អ្នក"],
  au_rcs_s: [
    "If you lose your phone, each code lets you sign in once. This is the only time the app shows them.",
    "បើបាត់ទូរស័ព្ទ លេខកូដនីមួយៗអនុញ្ញាតឱ្យចូលបានម្តង។ នេះជាលើកតែមួយគត់ដែលកម្មវិធីបង្ហាញវា។",
  ],
  au_rcs_keep: [
    "Write them on paper and keep them locked away from your phone. Do not save them in a photo or a chat.",
    "សរសេរលើក្រដាស ហើយទុកក្នុងកន្លែងចាក់សោ ឆ្ងាយពីទូរស័ព្ទ។ កុំរក្សាទុកក្នុងរូបថត ឬការជជែក។",
  ],
  au_rcs_copy: ["Copy codes", "ចម្លងលេខកូដ"],
  au_rcs_copied: [
    "Codes copied. Paste them only where you keep them safe.",
    "បានចម្លងលេខកូដ។ បិទភ្ជាប់តែកន្លែងដែលរក្សាទុកសុវត្ថិភាព។",
  ],
  au_rcs_ok: [
    "I wrote these codes down and keep them safe.",
    "ខ្ញុំបានកត់លេខកូដទាំងនេះ ហើយរក្សាទុកដោយសុវត្ថិភាព។",
  ],
  au_rcs_e: [
    "Tick the box to show you have kept the codes.",
    "សូមធីកប្រអប់ ដើម្បីបញ្ជាក់ថាអ្នកបានរក្សាទុកលេខកូដ។",
  ],
  au_rcs_go: ["Finish and open the app", "បញ្ចប់ ហើយបើកកម្មវិធី"],
  // New: set-up worked but the first recovery codes could not be made.
  au_rcs_none: [
    "Two-step sign-in is set up, but your recovery codes were not made. Make new codes in your account soon.",
    "ការចូលពីរជំហានបានរៀបចំរួច ប៉ុន្តែមិនទាន់បង្កើតលេខកូដសង្គ្រោះ។ សូមបង្កើតលេខកូដថ្មីឆាប់ៗ។",
  ],
  au_out_t: ["You were signed out", "អ្នកត្រូវបានចាកចេញ"],
  au_out_idle: [
    "Nobody used the app on this computer for 30 minutes, so it signed you out to keep the records safe.",
    "គ្មាននរណាប្រើកម្មវិធីលើកុំព្យូទ័រនេះ ៣០ នាទី ដូច្នេះវាបានចាកចេញ ដើម្បីការពារកំណត់ត្រា។",
  ],
  au_out_day: [
    "You were signed in for 24 hours. Everyone signs in again at least once a day.",
    "អ្នកបានចូលរយៈពេល ២៤ ម៉ោង។ អ្នករាល់គ្នាចូលម្តងទៀតយ៉ាងតិចម្តងក្នុងមួយថ្ងៃ។",
  ],
  au_out_note: [
    "Anything you had not saved was not saved. Sign in again to carry on.",
    "អ្វីដែលអ្នកមិនទាន់រក្សាទុក មិនត្រូវបានរក្សាទុកទេ។ សូមចូលម្តងទៀត ដើម្បីបន្ត។",
  ],
  au_again: ["Sign in again", "ចូលម្តងទៀត"],
  au_welcome: ["Signed in as {0}.", "បានចូលជា {0}។"],
  au_e_wait_n: [
    "Too many tries. Wait {0} minutes, then try again. If you forgot your password, ask the Owner.",
    "សាកច្រើនដងពេក។ សូមរង់ចាំ {0} នាទី រួចសាកម្តងទៀត។ បើភ្លេចពាក្យសម្ងាត់ សូមសួរម្ចាស់។",
  ],
  au_e_wait_1: [
    "Too many tries. Wait 1 minute, then try again. If you forgot your password, ask the Owner.",
    "សាកច្រើនដងពេក។ សូមរង់ចាំ ១ នាទី រួចសាកម្តងទៀត។ បើភ្លេចពាក្យសម្ងាត់ សូមសួរម្ចាស់។",
  ],
  // New: the 5-minute sign-in step (10 minutes for a new password) has ended.
  au_e_step_time: [
    "This step took too long. Sign in again to carry on.",
    "ជំហាននេះយូរពេក។ សូមចូលម្តងទៀត ដើម្បីបន្ត។",
  ],
  // New: no answer from the server.
  au_e_offline: [
    "The app could not reach the office computer. Try again.",
    "កម្មវិធីមិនអាចភ្ជាប់ទៅកុំព្យូទ័រការិយាល័យបានទេ។ សូមសាកម្តងទៀត។",
  ],
  // New (L6 review round 1): a request is running; the set-up picture is being fetched.
  au_working: ["Please wait…", "សូមរង់ចាំ…"],
  au_su_loading: ["Getting your QR code…", "កំពុងយក QR កូដរបស់អ្នក…"],
  me_out: ["Sign out", "ចាកចេញ"],
} as const satisfies Record<string, readonly [string, string]>;

export type TextKey = keyof typeof text;

const KHMER_DIGITS = "០១២៣៤៥៦៧៨៩";

/** Western digits as Khmer digits, for numbers shown inside Khmer text. */
export function khmerDigits(value: string): string {
  return value.replace(/[0-9]/g, (digit) => KHMER_DIGITS.charAt(Number(digit)));
}

/** The text of `key` in `language`, with `{0}` filled in; numbers in Khmer use Khmer digits. */
export function translate(
  language: Language,
  key: TextKey,
  argument?: string | number,
): string {
  const template = text[key][language === "en" ? 0 : 1];
  if (argument === undefined) return template;
  const filled =
    typeof argument === "number" && language === "km"
      ? khmerDigits(String(argument))
      : String(argument);
  // A function, so a "$" in a name is shown as typed (review round 1).
  return template.replace("{0}", () => filled);
}

export const LANGUAGE_STORAGE_KEY = "chetana.language";

/** The language chosen on this device; English when nothing (or nothing readable) is kept. */
export function storedLanguage(): Language {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) === "km"
      ? "km"
      : "en";
  } catch {
    return "en";
  }
}

/** Keeps the language choice on this device; it is not a secret. */
export function storeLanguage(language: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // A browser without storage keeps the choice for this page only.
  }
}
