// V1-058 R7a: the words of Waiting for approval in English and Khmer, from the owner's mock-up
// (i18n.js, i18n10.js, app10.js). Khmer needs the native check before the app is used. Lines
// marked "new" are not in the mock-up.

import type { Language } from "../signInText";
import type { WaitingDraft } from "./approvalsClient";

const TEXT = {
  ap_sub: [
    "Drafts move no money until the Owner or a Manager confirms them",
    "សេចក្តីព្រាងមិនផ្លាស់ទីប្រាក់ទេ រហូតដល់ម្ចាស់ ឬអ្នកគ្រប់គ្រងបញ្ជាក់",
  ],
  as_of: ["As of {0}", "គិតត្រឹមម៉ោង {0}"],
  // new
  loading: ["Loading the drafts…", "កំពុងផ្ទុកសេចក្តីព្រាង…"],
  // new
  failed: [
    "The drafts could not be read just now. Check the connection and try again.",
    "មិនអាចអានសេចក្តីព្រាងបានទេឥឡូវនេះ។ សូមពិនិត្យការតភ្ជាប់ ហើយព្យាយាមម្តងទៀត។",
  ],
  // new
  not_allowed: [
    "Your account cannot see the drafts. Use the menu to open your work.",
    "គណនីរបស់អ្នកមិនអាចមើលសេចក្តីព្រាងបានទេ។ សូមប្រើម៉ឺនុយ ដើម្បីបើកការងាររបស់អ្នក។",
  ],
  retry: ["Retry", "ព្យាយាមម្តងទៀត"],

  apc_wait: ["Waiting", "កំពុងរង់ចាំ"],
  apc_wait_s: ["Drafts to confirm", "សេចក្តីព្រាងត្រូវបញ្ជាក់"],
  apc_out: ["Money out", "ប្រាក់ចេញ"],
  apc_out_s: ["Refunds waiting", "ការសងប្រាក់កំពុងរង់ចាំ"],
  // new: a held-value refund gets its amount only at confirm.
  apc_out_unknown: [
    "Refunds waiting · {0} worked out at confirm",
    "ការសងប្រាក់កំពុងរង់ចាំ · {0} គណនាពេលបញ្ជាក់",
  ],
  apc_kept: ["Deposits kept", "ប្រាក់កក់ដែលរក្សាទុក"],
  apc_kept_s: ["Forfeitures waiting", "ការរឹបអូសកំពុងរង់ចាំ"],
  apc_done: ["Decided today", "បានសម្រេចថ្ងៃនេះ"],
  apc_done_s: ["Confirmed or rejected", "បានបញ្ជាក់ ឬបដិសេធ"],
  ap_showing: ["Showing: {0}", "កំពុងបង្ហាញ៖ {0}"],
  pc_clear: ["Show all", "បង្ហាញទាំងអស់"],

  ap_col_draft: ["Draft", "សេចក្តីព្រាង"],
  ap_col_for: ["For", "សម្រាប់"],
  ap_col_by: ["Prepared by", "រៀបចំដោយ"],
  ap_col_amt: ["Amount", "ចំនួន"],
  col_status: ["Status", "ស្ថានភាព"],
  ap_open: ["Open", "បើក"],
  ap_wait_chip: ["Waiting", "កំពុងរង់ចាំ"],
  ap_none: [
    "Nothing is waiting. Every draft has been decided.",
    "គ្មានអ្វីរង់ចាំទេ។ សេចក្តីព្រាងទាំងអស់បានសម្រេចហើយ។",
  ],
  ap_done_h: ["Decided today", "បានសម្រេចថ្ងៃនេះ"],
  ap_done_none: ["Nothing decided yet today.", "មិនទាន់មានការសម្រេចថ្ងៃនេះទេ។"],
  ap_rule: [
    "The person who prepared a draft may also confirm it only if they have approval rights. Both names are kept in History.",
    "អ្នករៀបចំសេចក្តីព្រាងអាចបញ្ជាក់វាបាន លុះត្រាតែមានសិទ្ធិអនុម័ត។ ឈ្មោះទាំងពីរត្រូវរក្សាក្នុងប្រវត្តិ។",
  ],
  // new: the list shows the first 200 drafts, oldest first.
  ap_more: [
    "Only the 200 oldest drafts are shown. Decide these first to see the rest.",
    "បង្ហាញតែសេចក្តីព្រាងចាស់បំផុត 200 ប៉ុណ្ណោះ។ សូមសម្រេចពួកវាមុន ដើម្បីមើលសេចក្តីព្រាងផ្សេងទៀត។",
  ],

  ap_confirm: ["Confirm", "បញ្ជាក់"],
  ap_reject: ["Reject", "បដិសេធ"],
  ap_withdraw: ["Withdraw", "ដកវិញ"],
  cancel: ["Cancel", "បោះបង់"],
  close: ["Close", "បិទ"],
  required: ["Required", "ចាំបាច់"],
  ap_reason: ["Reason", "មូលហេតុ"],
  ap_prepared: ["Prepared", "បានរៀបចំ"],
  df_res: ["Reservation", "ការកក់"],
  df_lease: ["Lease", "កិច្ចសន្យា"],
  ap_moves: ["What happens when you confirm", "អ្វីកើតឡើងពេលអ្នកបញ្ជាក់"],
  // The mock-up adds "In this mock-up you are the Owner."
  ap_lock: [
    "Only the Owner or a Manager can confirm.",
    "មានតែម្ចាស់ ឬអ្នកគ្រប់គ្រងទេដែលអាចបញ្ជាក់។",
  ],
  // new
  ap_lock_view: [
    "You can see this draft. Only the Owner or a Manager can confirm or reject it.",
    "អ្នកអាចមើលសេចក្តីព្រាងនេះបាន។ មានតែម្ចាស់ ឬអ្នកគ្រប់គ្រងទេដែលអាចបញ្ជាក់ ឬបដិសេធវា។",
  ],
  ap_by_at: ["{0} · {1}", "{0} · {1}"],
  ap_st_ok: ["Confirmed", "បានបញ្ជាក់"],
  ap_st_rej: ["Rejected", "បានបដិសេធ"],
  ap_st_wdr: ["Withdrawn", "បានដកវិញ"],
  ap_ok_toast: ["{0} confirmed.", "{0} បានបញ្ជាក់។"],
  ap_rej_toast: [
    "{0} rejected. No money moved.",
    "{0} ត្រូវបានបដិសេធ។ គ្មានប្រាក់ផ្លាស់ទីទេ។",
  ],
  ap_wdr_toast: [
    "{0} withdrawn. No money moved.",
    "{0} ត្រូវបានដកវិញ។ គ្មានប្រាក់ផ្លាស់ទីទេ។",
  ],

  ap_rej_t: ["Reject this draft", "បដិសេធសេចក្តីព្រាងនេះ"],
  ap_rej_why: ["Why is it rejected?", "ហេតុអ្វីបដិសេធ?"],
  ap_rej_e: ["Write why it is rejected.", "សូមសរសេរមូលហេតុដែលបដិសេធ។"],
  ap_rej_note: [
    "A rejected draft moves no money. The person who prepared it can prepare a new one.",
    "សេចក្តីព្រាងដែលបដិសេធមិនផ្លាស់ទីប្រាក់ទេ។ អ្នករៀបចំអាចរៀបចំថ្មីបាន។",
  ],
  // new: the server keeps a reason for a withdrawn draft too.
  ap_wdr_t: ["Withdraw this draft", "ដកសេចក្តីព្រាងនេះវិញ"],
  // new
  ap_wdr_why: ["Why do you withdraw it?", "ហេតុអ្វីអ្នកដកវាវិញ?"],
  // new
  ap_wdr_e: ["Write why you withdraw it.", "សូមសរសេរមូលហេតុដែលអ្នកដកវាវិញ។"],
  // new
  ap_wdr_note: [
    "A withdrawn draft moves no money. You can prepare a new one.",
    "សេចក្តីព្រាងដែលដកវិញមិនផ្លាស់ទីប្រាក់ទេ។ អ្នកអាចរៀបចំថ្មីបាន។",
  ],
  // new
  ap_unknown: [
    "The answer did not come back. Close this and look at the list before trying again.",
    "ចម្លើយមិនបានត្រឡប់មកវិញទេ។ សូមបិទ ហើយមើលបញ្ជីមុននឹងព្យាយាមម្តងទៀត។",
  ],

  dm_refund: [
    "The money is paid back to {0}. A Refund number is given now.",
    "ប្រាក់ត្រូវសងទៅ {0}។ លេខសងប្រាក់ត្រូវផ្តល់ឥឡូវ។",
  ],
  // new
  dm_refund_nobody: [
    "The money is paid back. A Refund number is given now.",
    "ប្រាក់ត្រូវសង។ លេខសងប្រាក់ត្រូវផ្តល់ឥឡូវ។",
  ],
  dm_keep: [
    "The Deposit is kept by CHETANA and counts as income this month.",
    "CHETANA រក្សាប្រាក់កក់ ហើយគិតជាចំណូលខែនេះ។",
  ],
  // new: the mock-up names the two Invoices.
  dm_move: [
    "The payment stays the same. It stops paying the wrong Invoice and pays the right one instead.",
    "ការបង់នៅដដែល។ វាឈប់បង់វិក្កយបត្រខុស ហើយបង់វិក្កយបត្រត្រឹមត្រូវវិញ។",
  ],
  // new
  dm_settle: [
    "The Final Settlement is closed as prepared. Any Deposit refund in it is paid back now.",
    "ការទូទាត់ចុងក្រោយត្រូវបិទតាមការរៀបចំ។ ប្រាក់កក់ដែលត្រូវសងក្នុងនោះត្រូវសងឥឡូវ។",
  ],
  // new
  dm_other: [
    "The records change as the draft says. The rules are checked again first.",
    "កំណត់ត្រាផ្លាស់ប្តូរតាមសេចក្តីព្រាង។ ច្បាប់ត្រូវពិនិត្យម្តងទៀតជាមុន។",
  ],

  dk_RES_REFUND: ["Refund: Reservation Deposit", "សងប្រាក់៖ ប្រាក់កក់ការកក់"],
  dk_RES_FORFEIT: ["Keep: Reservation Deposit", "រក្សាទុក៖ ប្រាក់កក់ការកក់"],
  dk_DEP_FORFEIT: ["Keep: Security Deposit", "រក្សាទុក៖ ប្រាក់កក់ធានា"],
  // new
  dk_PET_FORFEIT: ["Keep: Pet Deposit", "រក្សាទុក៖ ប្រាក់កក់សត្វចិញ្ចឹម"],
  dk_CREDIT_REFUND: ["Refund: Customer Credit", "សងប្រាក់៖ ឥណទានអតិថិជន"],
  // new
  dk_PAYMENT_REFUND: ["Refund: Payment", "សងប្រាក់៖ ការបង់ប្រាក់"],
  // new
  dk_REFUND: ["Refund", "សងប្រាក់"],
  dk_PAYMENT_MOVE: [
    "Move payment to the right Unit",
    "ផ្ទេរការបង់ទៅបន្ទប់ត្រឹមត្រូវ",
  ],
  // new
  dk_FORFEIT_UNDO: ["Undo: kept Deposit", "មិនធ្វើវិញ៖ ប្រាក់កក់ដែលរក្សាទុក"],
  // new
  dk_RECEIPT_UNDO: ["Undo: Deposit receipt", "មិនធ្វើវិញ៖ បង្កាន់ដៃប្រាក់កក់"],
  // new
  dk_DEPOSIT: ["Deposit decision", "ការសម្រេចប្រាក់កក់"],
  // new
  dk_PAYMENT_RETURN: [
    "Payment returned to the payer",
    "ការបង់ប្រាក់ត្រូវប្រគល់ទៅអ្នកបង់វិញ",
  ],
  // new
  dk_ADJUSTMENT_REVERSAL: [
    "Undo: Invoice adjustment",
    "មិនធ្វើវិញ៖ ការកែតម្រូវវិក្កយបត្រ",
  ],
  // new
  dk_FINAL_SETTLEMENT: ["Final Settlement", "ការទូទាត់ចុងក្រោយ"],
  // new
  dk_CORRECTION: ["Correction: {0}", "ការកែតម្រូវ៖ {0}"],
  // new
  dk_OTHER: ["Draft", "សេចក្តីព្រាង"],

  // new: what a Final Settlement correction changes.
  cv_EXTRA_CHARGE: ["extra charge", "ថ្លៃបន្ថែម"],
  cv_CHARGE_REDUCTION: ["lower a charge", "បន្ថយថ្លៃ"],
  cv_REFUND: ["refund", "សងប្រាក់"],
  cv_HELD_VALUE_REFUND: ["refund held money", "សងប្រាក់ដែលបានរក្សាទុក"],
  cv_PET_DAMAGE_RECLASSIFICATION: ["pet damage", "ការខូចខាតដោយសត្វចិញ្ចឹម"],
  cv_REFUND_RETURN: ["refund came back", "ប្រាក់សងត្រឡប់មកវិញ"],
  cv_FORFEITURE_REVERSAL: [
    "undo kept Deposit",
    "មិនធ្វើវិញ ប្រាក់កក់ដែលរក្សាទុក",
  ],
  cv_RETURNED_PAYMENT: ["returned payment", "ការបង់ប្រាក់ដែលបានប្រគល់វិញ"],
  cv_DEPOSIT_RECEIPT_CORRECTION: ["Deposit receipt", "បង្កាន់ដៃប្រាក់កក់"],
  cv_RETURN_REVERSAL: [
    "undo returned payment",
    "មិនធ្វើវិញ ការបង់ប្រាក់ដែលបានប្រគល់",
  ],
  cv_ADJUSTMENT_REVERSAL: [
    "undo Invoice adjustment",
    "មិនធ្វើវិញ ការកែតម្រូវវិក្កយបត្រ",
  ],
  cv_PAYMENT_MOVE: ["move payment", "ផ្ទេរការបង់ប្រាក់"],
  cv_other: ["other change", "ការផ្លាស់ប្តូរផ្សេង"],
} as const satisfies Record<string, readonly [string, string]>;

export type ApprovalsTextKey = keyof typeof TEXT;

/** The words for `key`, with {0}, {1} … filled in. */
export function apt(
  language: Language,
  key: ApprovalsTextKey,
  ...values: (string | number)[]
): string {
  const text = TEXT[key][language === "km" ? 1 : 0];
  return text.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

function correctionKey(variant: string | null): ApprovalsTextKey {
  const key = `cv_${variant ?? ""}`;
  return key in TEXT ? (key as ApprovalsTextKey) : "cv_other";
}

/** The plain name of a draft, from its kind and variant (DESIGN.md, mock-up dk_* labels). */
export function draftLabel(language: Language, draft: WaitingDraft): string {
  const variant = draft.summary.variant;
  const reservation =
    variant === "RESERVATION_OUTCOME" || variant === "RESERVATION_CORRECTION";
  switch (draft.kind) {
    case "REFUND": {
      if (reservation) return apt(language, "dk_RES_REFUND");
      const source = draft.payload.source_kind;
      if (variant === "CREDIT_CUSTOMER" || source === "CREDIT")
        return apt(language, "dk_CREDIT_REFUND");
      if (source === "PAYMENT") return apt(language, "dk_PAYMENT_REFUND");
      return apt(language, "dk_REFUND");
    }
    case "DEPOSIT_FORFEITURE":
      if (reservation) return apt(language, "dk_RES_FORFEIT");
      if (variant === "LEASE_FORFEITURE")
        return apt(
          language,
          draft.summary.deposit_type === "PET"
            ? "dk_PET_FORFEIT"
            : "dk_DEP_FORFEIT",
        );
      if (variant === "LEASE_FORFEITURE_REVERSAL")
        return apt(language, "dk_FORFEIT_UNDO");
      if (variant === "DEPOSIT_RECEIPT_REVERSAL")
        return apt(language, "dk_RECEIPT_UNDO");
      return apt(language, "dk_DEPOSIT");
    case "PAYMENT_MOVE":
      return apt(language, "dk_PAYMENT_MOVE");
    case "PAYMENT_RETURN":
      return apt(language, "dk_PAYMENT_RETURN");
    case "ADJUSTMENT_REVERSAL":
      return apt(language, "dk_ADJUSTMENT_REVERSAL");
    case "FINAL_SETTLEMENT":
      return apt(language, "dk_FINAL_SETTLEMENT");
    case "SETTLEMENT_CORRECTION":
      return apt(
        language,
        "dk_CORRECTION",
        apt(language, correctionKey(variant)),
      );
    default:
      return apt(language, "dk_OTHER");
  }
}

/** One line on what confirming does (mock-up draftEffect). */
export function draftEffect(language: Language, draft: WaitingDraft): string {
  const { direction, customer_name } = draft.summary;
  if (draft.kind === "FINAL_SETTLEMENT") return apt(language, "dm_settle");
  if (direction === "OUT")
    return customer_name === null
      ? apt(language, "dm_refund_nobody")
      : apt(language, "dm_refund", customer_name);
  if (direction === "KEPT") return apt(language, "dm_keep");
  if (draft.kind === "PAYMENT_MOVE") return apt(language, "dm_move");
  return apt(language, "dm_other");
}
