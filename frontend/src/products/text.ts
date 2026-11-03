// V1.1 part 4 (DL-121): the words of Building › Products, in English and Khmer. Khmer marked
// "new" needs the native check.

import type { Language } from "../signInText";

const TEXT = {
  loading: ["Loading…", "កំពុងផ្ទុក…"],
  failed: [
    "This list could not be read just now.",
    "មិនអាចអានបញ្ជីនេះបានទេឥឡូវនេះ។",
  ],
  retry: ["Try again", "សាកម្តងទៀត"],
  no_property: ["Choose the Property first.", "សូមជ្រើសរើសអចលនទ្រព្យជាមុនសិន។"],
  cancel: ["Cancel", "បោះបង់"],
  save: ["Save", "រក្សាទុក"],
  close: ["Close", "បិទ"],
  required: ["Required", "ត្រូវការ"],
  optional: ["Optional", "ស្រេចចិត្ត"],
  // Products tab
  pr_title: ["Products", "ផលិតផល"],
  pr_add: ["Add product", "បន្ថែមផលិតផល"],
  pr_rules: [
    "New products get a mark-up of {0} (minimum {1}, maximum {2}). Prices round up to the next {3}.",
    "ផលិតផលថ្មីទទួលបានការបូកបន្ថែម {0} (អប្បបរមា {1} អតិបរមា {2})។ តម្លៃបង្គត់ឡើងទៅ {3} បន្ទាប់។",
  ],
  pr_no_max: ["none", "គ្មាន"],
  pr_none: ["No products yet.", "មិនទាន់មានផលិតផលទេ។"],
  pr_sku: ["SKU", "លេខកូដ"],
  pr_name: ["Name", "ឈ្មោះ"],
  pr_category: ["Category", "ប្រភេទ"],
  pr_unit: ["Unit", "ឯកតា"],
  pr_stock: ["In stock", "ក្នុងស្តុក"],
  pr_cost: ["Cost", "ថ្លៃដើម"],
  pr_mark_up: ["Mark-up", "ការបូកបន្ថែម"],
  pr_price: ["Price", "តម្លៃ"],
  pr_actions: ["Actions", "សកម្មភាព"],
  pr_edit: ["Edit", "កែ"],
  pr_prices: ["Prices", "តម្លៃ"],
  pr_set_mark_up: ["Mark-up", "ការបូកបន្ថែម"],
  pr_set_cost: ["Cost", "ថ្លៃដើម"],
  pr_service: ["Service", "សេវា"],
  pr_discontinued: ["Discontinued", "ឈប់លក់"],
  pr_low: ["Low stock", "ស្តុកតិច"],
  pr_no_price: [
    "No price until the first Purchase",
    "គ្មានតម្លៃរហូតដល់ការទិញលើកដំបូង",
  ],
  pr_note: [
    "An Item's cost is its last Purchase cost. After a Purchase the app sets the price again when the real mark-up is below the minimum or above the maximum. A product is never deleted; mark it Discontinued.",
    "ថ្លៃដើមរបស់ទំនិញគឺថ្លៃទិញចុងក្រោយ។ ក្រោយការទិញ កម្មវិធីកំណត់តម្លៃម្តងទៀត នៅពេលការបូកបន្ថែមពិតទាបជាងអប្បបរមា ឬខ្ពស់ជាងអតិបរមា។ ផលិតផលមិនដែលត្រូវលុបទេ សូមសម្គាល់ថាឈប់លក់។",
  ],
  pr_added: ["{0} added.", "បានបន្ថែម {0}។"],
  pr_saved: ["{0} saved.", "បានរក្សាទុក {0}។"],
  // Product dialog
  pd_new_t: ["Add product", "បន្ថែមផលិតផល"],
  pd_edit_t: ["Edit {0}", "កែ {0}"],
  pd_name_en: ["Name in English", "ឈ្មោះជាភាសាអង់គ្លេស"],
  pd_name_kh: ["Name in Khmer", "ឈ្មោះជាភាសាខ្មែរ"],
  pd_description: ["Description", "ការពិពណ៌នា"],
  pd_reorder_level: ["Reorder level", "កម្រិតបញ្ជាទិញឡើងវិញ"],
  pd_reorder_qty: ["Reorder quantity", "បរិមាណបញ្ជាទិញឡើងវិញ"],
  pd_reorder_h: [
    "Low stock shows when the stock is at this level or below.",
    "ស្តុកតិចបង្ហាញនៅពេលស្តុកនៅកម្រិតនេះ ឬទាបជាង។",
  ],
  pd_service_cost: ["Cost of one", "ថ្លៃដើមមួយ"],
  pd_service_cost_h: [
    "A Service's cost is typed by a Manager or the Owner. The app sets the price from it.",
    "ថ្លៃដើមរបស់សេវាត្រូវវាយដោយអ្នកគ្រប់គ្រង ឬម្ចាស់។ កម្មវិធីកំណត់តម្លៃពីវា។",
  ],
  pd_item_cost_h: [
    "An Item gets its cost and price from its first Purchase.",
    "ទំនិញទទួលបានថ្លៃដើម និងតម្លៃពីការទិញលើកដំបូង។",
  ],
  pd_discontinued_h: [
    "A discontinued product cannot be bought again. Its stock can still be used, and you can switch it back.",
    "ផលិតផលដែលឈប់លក់មិនអាចទិញម្តងទៀតបានទេ។ ស្តុករបស់វានៅតែអាចប្រើបាន ហើយអ្នកអាចប្តូរវាវិញបាន។",
  ],
  e_name: [
    "Enter a name of 1 to 120 letters.",
    "បញ្ចូលឈ្មោះពី 1 ដល់ 120 តួអក្សរ។",
  ],
  e_whole: ["Enter a whole number, like 2.", "បញ្ចូលចំនួនគត់ ដូចជា 2។"],
  e_money: [
    "Enter an amount above 0, like 12.50.",
    "បញ្ចូលចំនួនលើស 0 ដូចជា 12.50។",
  ],
  e_percent: ["Enter a percent, like 20.", "បញ្ចូលភាគរយ ដូចជា 20។"],
  // Mark-ups and cost
  mu_t: ["Mark-up for {0}", "ការបូកបន្ថែមសម្រាប់ {0}"],
  mu_mark_up: ["Mark-up (%)", "ការបូកបន្ថែម (%)"],
  mu_min: ["Minimum (%)", "អប្បបរមា (%)"],
  mu_max: ["Maximum (%)", "អតិបរមា (%)"],
  mu_max_h: ["Leave empty for no maximum.", "ទុកទទេសម្រាប់គ្មានអតិបរមា។"],
  mu_range: [
    "The mark-up is between the minimum and the maximum.",
    "ការបូកបន្ថែមស្ថិតនៅចន្លោះអប្បបរមា និងអតិបរមា។",
  ],
  mu_preview: ["New price {0}", "តម្លៃថ្មី {0}"],
  sc_t: ["Cost of {0}", "ថ្លៃដើមរបស់ {0}"],
  ph_t: ["Prices of {0}", "តម្លៃរបស់ {0}"],
  ph_when: ["When", "ពេល"],
  ph_cause: ["Why", "មូលហេតុ"],
  ph_by: ["By", "ដោយ"],
  ph_none: ["No price yet.", "មិនទាន់មានតម្លៃទេ។"],
  ph_PURCHASE: ["Purchase", "ការទិញ"],
  ph_SERVICE_COST: ["Service cost", "ថ្លៃដើមសេវា"],
  ph_MARK_UP: ["Mark-up changed", "បានប្តូរការបូកបន្ថែម"],
  // Stock movements tab
  sm_title: ["Stock movements", "ចលនាស្តុក"],
  sm_purchase: ["New purchase", "ការទិញថ្មី"],
  sm_transfer: ["Move stock", "ផ្លាស់ទីស្តុក"],
  sm_adjust: ["Adjust stock", "កែតម្រូវស្តុក"],
  sm_none: ["No stock movements yet.", "មិនទាន់មានចលនាស្តុកទេ។"],
  sm_number: ["Number", "លេខ"],
  sm_date: ["Date", "កាលបរិច្ឆេទ"],
  sm_kind: ["Kind", "ប្រភេទ"],
  sm_product: ["Product", "ផលិតផល"],
  sm_qty: ["Qty", "ចំនួន"],
  sm_place: ["Place", "ទីតាំង"],
  sm_detail: ["Details", "ព័ត៌មានលម្អិត"],
  sm_by: ["By", "ដោយ"],
  sm_note: [
    "Stock movements are never changed or removed. A mistake is fixed with an Adjustment, which only a Manager or the Owner records. Stock never goes below 0.",
    "ចលនាស្តុកមិនដែលត្រូវបានប្តូរ ឬលុបទេ។ កំហុសត្រូវកែដោយការកែតម្រូវ ដែលមានតែអ្នកគ្រប់គ្រង ឬម្ចាស់ទេដែលកត់ត្រា។ ស្តុកមិនដែលទាបជាង 0 ទេ។",
  ],
  sm_PURCHASE: ["Purchase", "ការទិញ"],
  sm_ADJUSTMENT_IN: ["Adjustment in", "កែតម្រូវចូល"],
  sm_ADJUSTMENT_OUT: ["Adjustment out", "កែតម្រូវចេញ"],
  sm_TRANSFER_OUT: ["Transfer out", "ផ្ទេរចេញ"],
  sm_TRANSFER_IN: ["Transfer in", "ផ្ទេរចូល"],
  sm_saved: ["{0} saved.", "បានរក្សាទុក {0}។"],
  // Movement dialog
  md_purchase_t: ["New purchase", "ការទិញថ្មី"],
  md_transfer_t: ["Move stock", "ផ្លាស់ទីស្តុក"],
  md_adjust_t: ["Adjust stock", "កែតម្រូវស្តុក"],
  md_choose: ["Choose", "ជ្រើសរើស"],
  md_from: ["From", "ពី"],
  md_to: ["To", "ទៅ"],
  md_put_in: ["Put in", "ដាក់ក្នុង"],
  md_take_from: ["Take from", "យកពី"],
  md_in: [
    "Add to stock (found or counted more)",
    "បន្ថែមស្តុក (រកឃើញ ឬរាប់បានច្រើន)",
  ],
  md_out: ["Take out of stock (broken or lost)", "ដកចេញពីស្តុក (ខូច ឬបាត់)"],
  md_way: ["Which way", "ទិសដៅ"],
  md_unit_cost: ["Cost of one", "ថ្លៃដើមមួយ"],
  md_supplier: ["Supplier", "អ្នកផ្គត់ផ្គង់"],
  md_receipt: ["Receipt number", "លេខបង្កាន់ដៃ"],
  md_reason: ["Reason", "មូលហេតុ"],
  md_at_place: ["{0} here", "{0} នៅទីនេះ"],
  md_price_h: [
    "The price is now {0}. With this cost and a mark-up of {1}, it would be {2}.",
    "តម្លៃឥឡូវនេះគឺ {0}។ ជាមួយថ្លៃដើមនេះ និងការបូកបន្ថែម {1} វានឹងជា {2}។",
  ],
  e_product: ["Choose a product.", "សូមជ្រើសរើសផលិតផល។"],
  e_qty: ["Enter a quantity above 0 ({0}).", "បញ្ចូលបរិមាណលើស 0 ({0})។"],
  e_qty_whole: ["a whole number", "ចំនួនគត់"],
  e_qty_part: ["up to 3 decimals", "រហូតដល់ទសភាគ 3"],
  e_place: ["Choose a place.", "សូមជ្រើសរើសទីតាំង។"],
  e_same: [
    "Choose another place to move to.",
    "សូមជ្រើសរើសទីតាំងផ្សេងដើម្បីផ្លាស់ទៅ។",
  ],
  e_short: ["There is only {0} at this place.", "មានតែ {0} នៅទីតាំងនេះ។"],
  e_reason: ["Enter the reason.", "សូមបញ្ចូលមូលហេតុ។"],
  // Locations tab
  lo_title: ["Locations", "ទីតាំង"],
  lo_unit: ["Unit {0}", "បន្ទប់ {0}"],
  lo_not_for_rent: ["Not for rent", "មិនជួល"],
  lo_place: ["Place", "ទីតាំង"],
  lo_holds: ["Holds", "មាន"],
  lo_empty: ["Empty", "ទទេ"],
  lo_add_place: ["Add place", "បន្ថែមទីតាំង"],
  lo_none: [
    "No places yet. Add Unit features to a Unit first.",
    "មិនទាន់មានទីតាំងទេ។ សូមបន្ថែមលក្ខណៈបន្ទប់ទៅបន្ទប់មួយជាមុនសិន។",
  ],
  lo_note: [
    "A Location is a Unit plus one of its places. The Units for rent show here only when they hold items. A new kind of place is first added in Settings › Unit setup › Unit features.",
    "ទីតាំងគឺជាបន្ទប់មួយ បូកនឹងកន្លែងមួយរបស់វា។ បន្ទប់សម្រាប់ជួលបង្ហាញនៅទីនេះតែនៅពេលវាមានរបស់។ ប្រភេទទីតាំងថ្មីត្រូវបន្ថែមជាមុននៅក្នុង ការកំណត់ › ការរៀបចំបន្ទប់ › លក្ខណៈបន្ទប់។",
  ],
  ap_t: ["Add place to Unit {0}", "បន្ថែមទីតាំងទៅបន្ទប់ {0}"],
  ap_kind: ["Kind of place", "ប្រភេទទីតាំង"],
  ap_next: ["It will be {0}.", "វានឹងជា {0}។"],
  ap_saved: ["{0} added.", "បានបន្ថែម {0}។"],
  // Refusals
  f_right: [
    "Your account may not do this.",
    "គណនីរបស់អ្នកមិនអាចធ្វើការនេះបានទេ។",
  ],
  f_stale: [
    "Someone changed this product meanwhile. The list is read again; try once more.",
    "មានអ្នកផ្សេងបានប្តូរផលិតផលនេះ។ បញ្ជីត្រូវបានអានម្តងទៀត សូមសាកម្តងទៀត។",
  ],
  f_refused: ["Not saved: {0}", "មិនបានរក្សាទុក៖ {0}"],
  f_failed: [
    "This could not be saved just now. Try again.",
    "មិនអាចរក្សាទុកបានទេឥឡូវនេះ។ សូមសាកម្តងទៀត។",
  ],
} as const satisfies Record<string, readonly [string, string]>;

export type ProductsTextKey = keyof typeof TEXT;

/** The words in the chosen language, with {0}, {1} filled in. */
export function pt(
  language: Language,
  key: ProductsTextKey,
  ...values: (string | number)[]
): string {
  const words = TEXT[key][language === "km" ? 1 : 0];
  return words.replace(/\{(\d+)\}/g, (match, index: string) => {
    const value = values[Number(index)];
    return value === undefined ? match : String(value);
  });
}

const UNIT_NAMES: Record<string, readonly [string, string]> = {
  PIECE: ["Piece", "ដុំ"],
  SET: ["Set", "ឈុត"],
  PAIR: ["Pair", "គូ"],
  METRE: ["Metre", "ម៉ែត្រ"],
  KILOGRAM: ["Kilogram", "គីឡូក្រាម"],
  LITRE: ["Litre", "លីត្រ"],
  BOX: ["Box", "ប្រអប់"],
  PACK: ["Pack", "កញ្ចប់"],
  BOTTLE: ["Bottle", "ដប"],
  TIME: ["Time", "ដង"],
  HOUR: ["Hour", "ម៉ោង"],
  BAG: ["Bag", "ថង់"],
};

export function unitName(unit: string, language: Language): string {
  const names = UNIT_NAMES[unit];
  return names === undefined ? unit : names[language === "km" ? 1 : 0];
}
