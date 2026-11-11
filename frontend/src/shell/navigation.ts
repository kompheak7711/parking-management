// V1-058 R1: the menu of the signed-in app (DESIGN.md 0.29 "Menu, top bar and search").
// The groups and their order live only here, so a new menu order is a one-place change.

import type { Language } from "../signInText";

export type PageId =
  | "home"
  | "payments"
  | "invoices"
  | "quotations"
  | "utilities"
  | "approvals"
  | "units"
  | "problems"
  | "products"
  | "stock"
  | "locations"
  | "customers"
  | "reservations"
  | "visitreqs"
  | "shortstays"
  | "leases"
  | "letters"
  | "moveout"
  | "reports"
  | "history"
  | "settings"
  | "exreqs"
  | "expenses"
  | "bills"
  | "journal"
  | "needscheck"
  | "chart"
  | "statements"
  | "budget"
  | "fassets"
  | "bankcash"
  | "lclose"
  | "employees"
  | "loans"
  | "payroll"
  | "attendance"
  | "tglinks"
  | "tgcontact"
  | "tgfaq"
  | "tgnotices"
  | "tghealth"
  | "account";

export type IconName =
  | "home"
  | "payments"
  | "invoice"
  | "meter"
  | "check"
  | "units"
  | "box"
  | "wrench"
  | "customers"
  | "calendar"
  | "lease"
  | "list"
  | "moveout"
  | "reports"
  | "history"
  | "staff"
  | "settings"
  | "send";

export interface MenuItem {
  /** The page the menu link opens; with tabs, the first tab. */
  page: PageId;
  icon: IconName;
  /** The name in the menu, when it differs from the page name. */
  label?: readonly [string, string];
  /** Pages shown as tabs under one menu item (owner, 24/10/2026). */
  tabs?: readonly PageId[];
}

export interface MenuGroup {
  /** No label for the group that holds only Home. */
  label: readonly [string, string] | null;
  items: readonly MenuItem[];
}

// The menu the owner approved on 24/10/2026 (UX Design thread): Home, Daily work, Tenants,
// Building, Office. V1.1 pages (Visit requests, Birthdays, Unit care) are added after V1.
// Khmer names marked "new" are not in the mock-up yet and need the native check.
export const MENU: readonly MenuGroup[] = [
  { label: null, items: [{ page: "home", icon: "home" }] },
  {
    label: ["Daily work", "ការងារប្រចាំថ្ងៃ"],
    items: [
      { page: "payments", icon: "payments" },
      // V1.1 part 6 (DL-123): Quotations is a tab of Invoices.
      { page: "invoices", icon: "invoice", tabs: ["invoices", "quotations"] },
      { page: "utilities", icon: "meter" },
      { page: "approvals", icon: "check" },
    ],
  },
  {
    // new
    label: ["Tenants", "អ្នកជួល"],
    items: [
      {
        page: "reservations",
        icon: "calendar",
        // new
        label: ["Bookings", "ការកក់"],
        // Telegram bots step 3a (DL-171): Visit requests from the Customer bot.
        tabs: ["reservations", "visitreqs"],
      },
      // Daily and weekly rent (phase 6 step 2, mock-up round 28): Tenants › Short stays.
      { page: "shortstays", icon: "calendar" },
      {
        page: "leases",
        icon: "lease",
        tabs: ["leases", "letters", "moveout"],
      },
      { page: "customers", icon: "customers" },
    ],
  },
  {
    // new
    label: ["Building", "អគារ"],
    items: [
      { page: "units", icon: "units" },
      // V1.1 part 4 (DL-121): Building › Products with its three tabs.
      {
        page: "products",
        icon: "box",
        tabs: ["products", "stock", "locations"],
      },
      // V1.1 part 7 (DL-124): one list for Unit and Building problems.
      { page: "problems", icon: "wrench" },
    ],
  },
  {
    label: ["Office", "ការិយាល័យ"],
    items: [
      // General Ledger phase 6 step 6 (mock-up v76, Administration › Ledger): its tabs in the
      // mock-up's order. Every role sees Expense requests; the other tabs need ledger.read.
      {
        page: "exreqs",
        icon: "list",
        label: ["Ledger", "សៀវភៅបញ្ជី"],
        tabs: [
          "exreqs",
          "expenses",
          "bills",
          "journal",
          "needscheck",
          "chart",
          "statements",
          "budget",
          "fassets",
          "bankcash",
          "lclose",
        ],
      },
      // HRIS phase 6 (mock-up v69, round 23): Employees and payroll with its tabs. Users and
      // access stays in Settings › Users and sign-in for now.
      {
        page: "employees",
        icon: "staff",
        label: ["Employees and payroll", "បុគ្គលិក និងប្រាក់ខែ"],
        tabs: ["employees", "loans", "payroll", "attendance"],
      },
      // Telegram bots step 2c (DL-128, mock-up round 29): Office › Telegram, with Contact office
      // and FAQ from step 2d part 2 (DL-170), in the mock-up's tab order.
      {
        page: "tglinks",
        icon: "send",
        label: ["Telegram", "តេឡេក្រាម"],
        tabs: ["tglinks", "tgcontact", "tgfaq", "tgnotices", "tghealth"],
      },
      { page: "reports", icon: "reports" },
      { page: "history", icon: "history" },
      { page: "settings", icon: "settings" },
    ],
  },
];

// Page names in English and Khmer, from the mock-up (i18n.js, i18n10.js). Khmer needs the
// native check before the app is used.
const PAGE_NAMES: Record<PageId, readonly [string, string]> = {
  home: ["Home", "ទំព័រដើម"],
  payments: ["Payments", "ការបង់ប្រាក់"],
  invoices: ["Invoices", "វិក្កយបត្រ"],
  quotations: ["Quotations", "សម្រង់តម្លៃ"],
  utilities: ["Utilities", "ទឹកភ្លើង"],
  approvals: ["Waiting for approval", "រង់ចាំការអនុម័ត"],
  units: ["Units", "បន្ទប់"],
  problems: ["Problem reports", "របាយការណ៍បញ្ហា"],
  // new
  products: ["Products", "ផលិតផល"],
  // new
  stock: ["Stock movements", "ចលនាស្តុក"],
  // new
  locations: ["Locations", "ទីតាំង"],
  customers: ["Customers", "អតិថិជន"],
  reservations: ["Reservations", "ការកក់ទុក"],
  visitreqs: ["Visit requests", "សំណើមកមើលបន្ទប់"],
  // new
  shortstays: ["Short stays", "ការស្នាក់នៅខ្លី"],
  leases: ["Leases", "កិច្ចសន្យាជួល"],
  letters: ["Letters", "លិខិត"],
  moveout: ["Move-out", "ការចាកចេញ"],
  reports: ["Reports", "របាយការណ៍"],
  history: ["History", "ប្រវត្តិ"],
  settings: ["Settings", "ការកំណត់"],
  exreqs: ["Expense requests", "សំណើចំណាយ"],
  expenses: ["Expenses", "ចំណាយ"],
  bills: ["Supplier bills", "វិក្កយបត្រអ្នកផ្គត់ផ្គង់"],
  journal: ["Journal entries", "ធាតុទិនានុប្បវត្តិ"],
  needscheck: ["Needs check", "ត្រូវពិនិត្យ"],
  chart: ["Chart of accounts", "តារាងគណនី"],
  statements: ["Financial statements", "របាយការណ៍ហិរញ្ញវត្ថុ"],
  budget: ["Budget", "ថវិកា"],
  fassets: ["Fixed assets", "ទ្រព្យសកម្មរយៈពេលវែង"],
  bankcash: ["Bank and cash", "ធនាគារ និងសាច់ប្រាក់"],
  lclose: ["Month-end close", "ការបិទចុងខែ"],
  employees: ["Employees", "បុគ្គលិក"],
  loans: ["Salary loans", "ប្រាក់កម្ចីប្រាក់ខែ"],
  payroll: ["Payroll", "បញ្ជីប្រាក់ខែ"],
  attendance: ["Attendance", "វត្តមាន"],
  tglinks: ["Linked tenants", "អ្នកជួលដែលបានភ្ជាប់"],
  tgcontact: ["Contact office", "ទាក់ទងការិយាល័យ"],
  tgfaq: ["FAQ", "សំណួរញឹកញាប់"],
  // DL-216; Khmer new.
  tgnotices: ["Notices", "សេចក្តីជូនដំណឹង"],
  tghealth: ["Telegram health", "ស្ថានភាពតេឡេក្រាម"],
  // new
  account: ["My account", "គណនីរបស់ខ្ញុំ"],
};

// V1-058 R1b (UI-008, owner 24/10/2026): a menu item shows only to a person who holds one of
// these capabilities; null means everyone who is signed in. Display only: every route still
// checks the capability on the server. Decided by Claude under the owner's 2026-10-23 22:30
// rule, except Waiting for approval and Settings, which follow the owner's words.
const PAGE_NEEDS: Record<PageId, readonly string[] | null> = {
  home: null,
  payments: [
    "payments.read",
    "payments.record",
    "receipts.read",
    "credits.read",
    "refunds.read",
  ],
  invoices: ["invoices.read"],
  // V1.1 part 6 (DL-123).
  quotations: ["quotations.read"],
  utilities: ["utility.read"],
  approvals: ["financial.approve"],
  units: ["units.read"],
  // V1.1 part 7 (DL-124).
  problems: ["problem_reports.read"],
  // V1.1 part 4 (DL-121): every Products tab reads with products.read.
  products: ["products.read"],
  stock: ["products.read"],
  locations: ["products.read"],
  customers: ["customers.read"],
  reservations: ["reservations.read"],
  // Telegram bots step 3a (DL-171): the Owner, the Manager and Staff.
  visitreqs: ["visit_requests.read"],
  // Daily and weekly rent: the calendar and bookings read with short_stays.read.
  shortstays: ["short_stays.read"],
  leases: ["leases.read"],
  letters: ["rent_nonpayment.read", "leases.warn"],
  moveout: ["deposits.read", "final_settlements.prepare", "leases.move_out"],
  // V1-060 B6: anyone who may read one report (frontend/src/reports/reportsData.ts REPORTS;
  // Unit occupancy also needs leases.read).
  reports: ["reports.read", "utility.read", "leases.read", "audit.view"],
  history: ["audit.view"],
  // V1-058 R7b: System health is a Settings tab for operations.status.read too.
  settings: [
    "settings.manage",
    "identity.manage_access",
    "operations.status.read",
  ],
  // General Ledger (owner plan 03/11/2026, rights table L1): Owner and Manager read the ledger.
  exreqs: ["expenses.request"],
  expenses: ["ledger.read"],
  bills: ["ledger.read"],
  journal: ["ledger.read"],
  needscheck: ["ledger.read"],
  chart: ["ledger.read"],
  statements: ["ledger.read"],
  budget: ["ledger.read"],
  fassets: ["ledger.read"],
  bankcash: ["ledger.read"],
  lclose: ["ledger.read"],
  // HRIS phase 6 (rights table, DB plan 03/11/2026): each tab needs its read right.
  employees: ["hr.employees.read"],
  loans: ["hr.salaries.read"],
  payroll: ["hr.salaries.read"],
  attendance: ["hr.attendance.read"],
  // Telegram bots step 2c (DL-128): Owner and Manager for now.
  tglinks: ["telegram.read"],
  tgcontact: ["telegram.contact"],
  tgfaq: ["telegram.faq", "telegram.contact"],
  tgnotices: ["telegram.read"],
  tghealth: ["telegram.read"],
  account: null,
};

/** May the person see this page? Unknown access (null) shows everything. */
export function pageAllowed(
  page: PageId,
  capabilities: ReadonlySet<string> | null,
): boolean {
  const needs = PAGE_NEEDS[page];
  if (needs === null || capabilities === null) return true;
  return needs.some((capability) => capabilities.has(capability));
}

/** The pages of a menu item the person may see, in tab order. */
export function allowedPagesOf(
  item: MenuItem,
  capabilities: ReadonlySet<string> | null,
): PageId[] {
  return (item.tabs ?? [item.page]).filter((page) =>
    pageAllowed(page, capabilities),
  );
}

export const PAGE_IDS = Object.keys(PAGE_NAMES) as PageId[];

export function pageName(page: PageId, language: Language): string {
  return PAGE_NAMES[page][language === "en" ? 0 : 1];
}

export function menuItemName(item: MenuItem, language: Language): string {
  return item.label === undefined
    ? pageName(item.page, language)
    : item.label[language === "en" ? 0 : 1];
}

/** The menu item that holds a page, directly or as one of its tabs; null for My account. */
export function menuItemFor(page: PageId): MenuItem | null {
  for (const group of MENU) {
    for (const item of group.items) {
      if (item.page === page || item.tabs?.includes(page) === true) return item;
    }
  }
  return null;
}

export function groupLabel(group: MenuGroup, language: Language): string {
  return group.label === null ? "" : group.label[language === "en" ? 0 : 1];
}

export function isPageId(value: string): value is PageId {
  return Object.prototype.hasOwnProperty.call(PAGE_NAMES, value);
}

/**
 * The page named by an address such as "#/units" or "#/units/<Unit id>"; Home for anything
 * else.
 */
export function pageFromHash(hash: string): PageId {
  const name = hash.replace(/^#\/?/, "").split("/")[0] ?? "";
  return isPageId(name) ? name : "home";
}

/** V1-058 R2: the record an address opens inside its page ("#/units/<id>"), or null. */
export function detailFromHash(hash: string): string | null {
  const parts = hash.replace(/^#\/?/, "").split("/");
  if (parts.length < 2 || !isPageId(parts[0] ?? "")) return null;
  let detail: string;
  try {
    detail = decodeURIComponent(parts.slice(1).join("/"));
  } catch {
    // A broken address such as "#/units/%E0" opens the page itself.
    return null;
  }
  return detail === "" ? null : detail;
}

export function hashForPage(page: PageId, detail?: string): string {
  return detail === undefined
    ? `#/${page}`
    : `#/${page}/${encodeURIComponent(detail)}`;
}
