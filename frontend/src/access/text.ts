// V1.1 part 3 (DL-120): the words of Roles and permissions, in English and Khmer.

import type { Language } from "../signInText";
import { singular } from "../shell/plural";

const TEXT = {
  ro_title: ["Roles", "តួនាទី"],
  ro_add: ["Add role", "បន្ថែមតួនាទី"],
  ro_role: ["Role", "តួនាទី"],
  ro_users: ["Users", "អ្នកប្រើ"],
  ro_perms: ["Permissions", "សិទ្ធិ"],
  ro_two_step: ["Two-step sign-in", "ការចូលពីរជំហាន"],
  ro_required: ["Required", "ត្រូវការ"],
  ro_optional: ["Optional", "ស្រេចចិត្ត"],
  ro_of: ["{0} of {1}", "{0} ក្នុង {1}"],
  ro_edit: ["Edit", "កែ"],
  ro_off: ["Turned off", "បានបិទ"],
  ro_note: [
    "A person may have several roles and gets every permission of each. Changes work at once; anyone who loses a permission is signed out.",
    "មនុស្សម្នាក់អាចមានតួនាទីច្រើន ហើយទទួលបានសិទ្ធិទាំងអស់នៃតួនាទីនីមួយៗ។ ការប្តូរមានប្រសិទ្ធភាពភ្លាមៗ អ្នកដែលបាត់សិទ្ធិត្រូវចាកចេញ។",
  ],
  ro_new_t: ["Add role", "បន្ថែមតួនាទី"],
  ro_edit_t: ["Edit role: {0}", "កែតួនាទី៖ {0}"],
  ro_name: ["Name in English", "ឈ្មោះជាភាសាអង់គ្លេស"],
  ro_name_kh: ["Name in Khmer", "ឈ្មោះជាភាសាខ្មែរ"],
  ro_owner_name: [
    "The Owner role keeps its name and is never turned off.",
    "តួនាទីម្ចាស់រក្សាឈ្មោះរបស់វា ហើយមិនដែលត្រូវបានបិទទេ។",
  ],
  ro_some: ["Part of it", "មួយផ្នែក"],
  ro_users_lock: [
    "Only the Owner manages users and roles.",
    "មានតែម្ចាស់ទេដែលគ្រប់គ្រងអ្នកប្រើ និងតួនាទី។",
  ],
  ro_rules_h: [
    "A role with this needs two-step sign-in. A Staff account gets it only after setting up its sign-in code.",
    "តួនាទីដែលមានសិទ្ធិនេះត្រូវការការចូលពីរជំហាន។ គណនីបុគ្គលិកទទួលបានវាលុះត្រាតែបានរៀបចំលេខកូដចូលរួច។",
  ],
  ro_turn_off: ["Turn this role off", "បិទតួនាទីនេះ"],
  ro_turn_off_h: [
    "A turned-off role gives nothing and cannot be given.",
    "តួនាទីដែលបានបិទមិនផ្តល់អ្វីទេ ហើយមិនអាចផ្តល់ឱ្យបានទេ។",
  ],
  ro_turn_off_users: [
    "A role with users cannot be turned off. Give them another role first.",
    "តួនាទីដែលមានអ្នកប្រើមិនអាចបិទបានទេ។ សូមផ្តល់តួនាទីផ្សេងឱ្យពួកគេជាមុនសិន។",
  ],
  ro_e_name: ["Write the name in English.", "សូមសរសេរឈ្មោះជាភាសាអង់គ្លេស។"],
  ro_e_taken: [
    "Another role already has this name.",
    "តួនាទីផ្សេងមានឈ្មោះនេះរួចហើយ។",
  ],
  ro_saved: ["Role saved: {0}", "បានរក្សាទុកតួនាទី៖ {0}"],
  ur_roles_col: ["Roles", "តួនាទី"],
  ur_roles_btn: ["Change", "ប្តូរ"],
  ur_roles_t: ["Roles for {0}", "តួនាទីសម្រាប់ {0}"],
  ur_roles_legend: ["Roles", "តួនាទី"],
  ur_owner_keeps: [
    "The Owner always keeps the Owner role.",
    "ម្ចាស់តែងតែរក្សាតួនាទីម្ចាស់។",
  ],
  ur_roles_reason_h: [
    "Needed when a role is taken away. It is kept in the audit log.",
    "ត្រូវការនៅពេលដកតួនាទីចេញ។ វាត្រូវបានរក្សាទុកក្នុងប្រវត្តិ។",
  ],
  ur_roles_code: [
    "{0}: a Staff account gets a role that changes business rules only after it has set up its sign-in code.",
    "{0}៖ គណនីបុគ្គលិកទទួលបានតួនាទីដែលប្តូរច្បាប់អាជីវកម្ម លុះត្រាតែបានរៀបចំលេខកូដចូលរួច។",
  ],
  ur_roles_one: ["{0}: not changed.", "{0}៖ មិនបានប្តូរទេ។"],
  ur_roles_none: ["No role", "គ្មានតួនាទី"],
  se_signin_roles: [
    "Two-step sign-in is needed for the Owner and for every role that can change business rules.",
    "ការចូលពីរជំហានត្រូវការសម្រាប់ម្ចាស់ និងសម្រាប់តួនាទីទាំងអស់ដែលអាចប្តូរច្បាប់អាជីវកម្ម។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type AccessTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function at(
  language: Language,
  key: AccessTextKey,
  ...values: (string | number)[]
): string {
  const words = TEXT[key][language === "km" ? 1 : 0];
  return singular(
    values.reduce<string>(
      (text, value, index) => text.replace(`{${String(index)}}`, String(value)),
      words,
    ),
  );
}
