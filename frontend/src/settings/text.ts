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
  se_tab_units: ["Unit setup", "ការរៀបចំបន្ទប់"],
  se_tab_users: ["Users and sign-in", "អ្នកប្រើ និងការចូល"],
  se_tab_health: ["System health", "សុខភាពប្រព័ន្ធ"],
  // new: tabs not rebuilt yet keep the earlier forms.
  earlier: ["Earlier forms (English)", "ទម្រង់មុន (អង់គ្លេស)"],
  // new
  earlier_note: [
    "This tab is rebuilt in a later step. Until then the earlier forms below still work.",
    "ផ្ទាំងនេះនឹងរៀបចំឡើងវិញនៅជំហានក្រោយ។ រហូតដល់ពេលនោះ ទម្រង់មុនខាងក្រោមនៅតែប្រើបាន។",
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
