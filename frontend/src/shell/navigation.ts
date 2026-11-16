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
  | "inspections"
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
  | "access"
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
  | "send"
  | "clip";

export interface MenuItem {
  /** The page the menu link opens; with tabs, the first tab. */
  page: PageId;
  icon: IconName;
  /** The name in the menu, when it differs from the page name. */
  label?: readonly [string, string];
  /** Pages shown as tabs under one menu item (owner, 24/10/2026). */
  tabs?: readonly PageId[];
  /** Owner 16/11/2026 (Ledger, 11 tabs -> 5): the tabs are these groups of pages; a switch
   *  under the tab row picks the page inside the open group. */
  groups?: readonly TabGroup[];
}

export interface TabGroup {
  id: string;
  label: readonly [string, string];
  /** The group's pages, in switch order; `tabs` above lists the same pages. */
  pages: readonly PageId[];
}

/** A tab group the person may see, with only the pages they may open. */
export interface AllowedGroup {
  id: string;
  label: string;
  pages: PageId[];
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
    label: ["Operations", "ប្រតិបត្តិការ"],
    items: [
      { page: "payments", icon: "payments" },
      // V1.1 part 6 (DL-123): Quotations is a tab of Invoices.
      { page: "invoices", icon: "invoice", tabs: ["invoices", "quotations"] },
      { page: "utilities", icon: "meter" },
      { page: "approvals", icon: "check" },
    ],
  },
  {
    // UI v81 (02/11 wording review): Tenants → Leasing.
    label: ["Leasing", "ការជួល"],
    // Leasing batch (owner 13/11/2026): Viewing requests; Long stays (Reservations, Leases,
    // Move-outs); Short stays with its in-page tabs as sub-items; Notices for every stay;
    // Customers.
    items: [
      // Telegram bots step 3a (DL-171): Visit requests from the Customer bot.
      { page: "visitreqs", icon: "calendar" },
      {
        page: "reservations",
        icon: "lease",
        // new: the Khmer word needs the native check.
        label: ["Long stays", "ការស្នាក់នៅយូរ"],
        tabs: ["reservations", "leases", "moveout"],
      },
      // Daily and weekly rent (phase 6 step 2): its tabs are sub-items (PAGE_SUB_TABS).
      { page: "shortstays", icon: "calendar" },
      { page: "letters", icon: "list" },
      { page: "customers", icon: "customers" },
    ],
  },
  {
    // UI v81: Building → Property.
    label: ["Property", "អចលនទ្រព្យ"],
    // UI v81 round 2 (owner 07/11/2026): the design's order, Inspections after Units.
    items: [
      { page: "units", icon: "units" },
      { page: "inspections", icon: "clip" },
      // V1.1 part 7 (DL-124): one list for Unit and Building problems.
      { page: "problems", icon: "wrench" },
      // V1.1 part 4 (DL-121): Building › Products with its three tabs.
      {
        page: "products",
        icon: "box",
        tabs: ["products", "stock", "locations"],
      },
    ],
  },
  {
    label: ["Administration", "រដ្ឋបាល"],
    // UI v81 round 2: the design's order, Reports and the Audit log before Staff.
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
        // Owner 16/11/2026 (picked on the card): 11 tabs become 5 groups. Khmer group names are
        // new and need the native check.
        groups: [
          {
            id: "spending",
            label: ["Spending", "ការចំណាយ"],
            pages: ["exreqs", "expenses", "bills"],
          },
          {
            id: "books",
            label: ["Books", "សៀវភៅបញ្ជី"],
            pages: ["journal", "needscheck", "chart"],
          },
          {
            id: "reports",
            label: ["Reports", "របាយការណ៍"],
            pages: ["statements", "budget"],
          },
          {
            id: "assets",
            label: ["Assets and cash", "ទ្រព្យ និងសាច់ប្រាក់"],
            pages: ["fassets", "bankcash"],
          },
          {
            id: "close",
            label: ["Month-end close", "ការបិទចុងខែ"],
            pages: ["lclose"],
          },
        ],
      },
      { page: "reports", icon: "reports" },
      { page: "history", icon: "history" },
      // HRIS phase 6 (mock-up v69, round 23): the Employees, Loans, Payroll and Attendance tabs.
      // UI v81 round 2 (owner 07/11/2026): the menu item is "Staff"; the Khmer word is new and
      // needs the native check.
      {
        page: "employees",
        icon: "staff",
        label: ["Staff", "បុគ្គលិក"],
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
      // UI v81 (B4): Users and access is its own menu item, moved out of Settings.
      { page: "access", icon: "customers" },
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
  approvals: ["Approvals", "ការអនុម័ត"],
  units: ["Units", "បន្ទប់"],
  // UI v81 round 2 (design v81 menu); the Khmer word is new and needs the native check.
  inspections: ["Inspections", "ការត្រួតពិនិត្យ"],
  problems: ["Problem reports", "របាយការណ៍បញ្ហា"],
  // new
  products: ["Products", "ផលិតផល"],
  // new
  stock: ["Stock movements", "ចលនាស្តុក"],
  // new
  locations: ["Storage locations", "ទីតាំងស្តុក"],
  customers: ["Customers", "អតិថិជន"],
  reservations: ["Reservations", "ការកក់ទុក"],
  visitreqs: ["Viewing requests", "សំណើមើលបន្ទប់"],
  // new
  shortstays: ["Short stays", "ការស្នាក់នៅខ្លី"],
  leases: ["Leases", "កិច្ចសន្យាជួល"],
  letters: ["Notices", "សេចក្ដីជូនដំណឹង"],
  moveout: ["Move-outs", "ការចាកចេញ"],
  reports: ["Reports", "របាយការណ៍"],
  history: ["Audit log", "កំណត់ហេតុសវនកម្ម"],
  settings: ["Settings", "ការកំណត់"],
  // new
  access: ["Users and access", "អ្នកប្រើ និងសិទ្ធិ"],
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
  // UI v81 round 2: Inspections belong to the Units (Joint Inspections at move-in and move-out,
  // Unit Checks during a Lease), so whoever reads Units sees the page.
  inspections: ["units.read"],
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
  letters: ["rent_nonpayment.read", "leases.warn", "short_stays.read"],
  moveout: ["deposits.read", "final_settlements.prepare", "leases.move_out"],
  // V1-060 B6: anyone who may read one report (frontend/src/reports/reportsData.ts REPORTS;
  // Unit occupancy also needs leases.read).
  reports: ["reports.read", "utility.read", "leases.read", "audit.view"],
  history: ["audit.view"],
  // V1-058 R7b: System health is a Settings tab for operations.status.read too.
  settings: ["settings.manage", "operations.status.read"],
  access: ["identity.manage_access"],
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

/** The tab groups of a menu item the person may see (empty groups left out); none without groups. */
export function allowedGroupsOf(
  item: MenuItem,
  capabilities: ReadonlySet<string> | null,
  language: Language,
): AllowedGroup[] {
  return (item.groups ?? []).flatMap((group) => {
    const pages = group.pages.filter((page) => pageAllowed(page, capabilities));
    return pages.length === 0
      ? []
      : [
          {
            id: group.id,
            label: group.label[language === "en" ? 0 : 1],
            pages,
          },
        ];
  });
}

// Owner 16/11/2026: inside the Spending group the first page is just "Requests".
const SWITCH_NAMES: Partial<Record<PageId, readonly [string, string]>> = {
  exreqs: ["Requests", "សំណើ"],
};

/** A page's name on the switch inside a tab group. */
export function switchName(page: PageId, language: Language): string {
  const short = SWITCH_NAMES[page];
  return short === undefined
    ? pageName(page, language)
    : short[language === "en" ? 0 : 1];
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
  const name = stripQuery(hash).replace(/^#\/?/, "").split("/")[0] ?? "";
  return isPageId(name) ? name : "home";
}

/** V1-058 R2: the record an address opens inside its page ("#/units/<id>"), or null. */
export function detailFromHash(hash: string): string | null {
  const parts = stripQuery(hash).replace(/^#\/?/, "").split("/");
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

/** UI v81 (B2): an address may end with "?tab=<sub-tab>"; the page and record ignore it. */
function stripQuery(hash: string): string {
  const at = hash.indexOf("?");
  return at < 0 ? hash : hash.slice(0, at);
}

/** UI v81 (B2): the sub-tab kept in the address ("#/settings?tab=rates"), or null. */
export function subTabFromHash(hash: string): string | null {
  return queryFromHash(hash, "tab");
}

/**
 * UI v81 round 3: one value kept after "?" in the address ("#/home?tasks=overdue" gives
 * "overdue" for "tasks"), or null when the address has none.
 */
export function queryFromHash(hash: string, key: string): string | null {
  const at = hash.indexOf("?");
  if (at < 0) return null;
  return new URLSearchParams(hash.slice(at + 1)).get(key);
}

export function hashForPage(page: PageId, detail?: string): string {
  return detail === undefined
    ? `#/${page}`
    : `#/${page}/${encodeURIComponent(detail)}`;
}

/**
 * UI v81 (owner 08/11/2026, section D item 14): the sub-tabs inside one page, shown as the menu
 * item's sub-items. A sub-item links to the same address as the sub-tab row writes
 * ("#/access?tab=roles"), so no address changes. The ids and names are the pages' own
 * (access, settings/text.ts); a sub-tab shows only to a person who holds one of its
 * capabilities (null: everyone who sees the page). Approvals has one view since DL-222
 * (owner 12/11/2026: a short-stay damage charge needs no approval), so it has no sub-items.
 */
export interface PageSubTab {
  id: string;
  label: readonly [string, string];
  needs?: readonly string[];
}

const PAGE_SUB_TABS: Partial<Record<PageId, readonly PageSubTab[]>> = {
  // Leasing batch (owner 13/11/2026): the Short stays tabs (shortstays/text.ts tab_*). Owner
  // 13/11 evening: the Weekly report moved to Reports and Booking sites to Settings.
  shortstays: [
    { id: "cal", label: ["Calendar", "ប្រតិទិន"] },
    { id: "list", label: ["Bookings", "ការកក់"] },
    { id: "clean", label: ["Housekeeping", "ការសម្អាត"] },
  ],
  access: [
    { id: "users", label: ["Users", "អ្នកប្រើ"] },
    { id: "roles", label: ["Roles", "តួនាទី"] },
    { id: "signin", label: ["Sign-in and security", "ការចូល និងសុវត្ថិភាព"] },
    { id: "history", label: ["History", "ប្រវត្តិ"] },
  ],
  settings: [
    {
      id: "business",
      label: ["Business", "អាជីវកម្ម"],
      needs: ["settings.manage"],
    },
    {
      id: "rates",
      label: ["Utility rates", "អត្រាទឹកភ្លើង"],
      needs: ["settings.manage"],
    },
    {
      id: "services",
      label: ["Monthly services", "សេវាប្រចាំខែ"],
      needs: ["settings.manage"],
    },
    {
      id: "units",
      label: ["Unit setup", "ការរៀបចំបន្ទប់"],
      needs: ["settings.manage"],
    },
    {
      id: "sites",
      label: ["Booking sites", "គេហទំព័រកក់"],
      needs: ["short_stays.approve"],
    },
    {
      id: "health",
      label: ["System health", "សុខភាពប្រព័ន្ធ"],
      needs: ["settings.manage", "operations.status.read"],
    },
  ],
};

/** One sub-item of a menu item: a page tab or an in-page sub-tab. */
export interface SubItem {
  key: string;
  href: string;
  label: string;
  /** The open page (and sub-tab) is this one. */
  current: boolean;
}

/**
 * The sub-items of a menu item the person may see: its page tabs (Leases → Leases, Notices,
 * Move-outs) or its in-page sub-tabs (Users and access → Users, Roles, …).
 * Fewer than two means the item has no "⌄". `tab` is the sub-tab in the address, null for the
 * page's first one.
 */
export function subItemsOf(
  item: MenuItem,
  page: PageId,
  tab: string | null,
  capabilities: ReadonlySet<string> | null,
  language: Language,
): SubItem[] {
  const groups = allowedGroupsOf(item, capabilities, language);
  const first = groups[0];
  if (groups.length > 1 || (first !== undefined && first.pages.length > 1)) {
    return groups.map((group) => ({
      key: group.id,
      href: hashForPage(group.pages[0] ?? item.page),
      label: group.label,
      current: group.pages.includes(page),
    }));
  }
  const pages = allowedPagesOf(item, capabilities);
  if (pages.length > 1) {
    return pages.map((tabPage) => ({
      key: tabPage,
      href: hashForPage(tabPage),
      label: pageName(tabPage, language),
      current: tabPage === page,
    }));
  }
  const subTabs = (PAGE_SUB_TABS[item.page] ?? []).filter(
    (subTab) =>
      subTab.needs === undefined ||
      capabilities === null ||
      subTab.needs.some((capability) => capabilities.has(capability)),
  );
  if (subTabs.length < 2) return [];
  const here = item.page === page;
  return subTabs.map((subTab, index) => ({
    key: subTab.id,
    href: `${hashForPage(item.page)}?tab=${encodeURIComponent(subTab.id)}`,
    label: subTab.label[language === "en" ? 0 : 1],
    current: here && (tab === null ? index === 0 : tab === subTab.id),
  }));
}

/** The key a menu group is remembered under (folded or open) on the device. */
export function menuGroupKey(group: MenuGroup): string {
  return group.label === null ? "home" : group.label[0].toLowerCase();
}
