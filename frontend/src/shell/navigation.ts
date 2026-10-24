// V1-058 R1: the menu of the signed-in app (DESIGN.md 0.29 "Menu, top bar and search").
// The groups and their order live only here, so a new menu order is a one-place change.

import type { Language } from "../signInText";

export type PageId =
  | "home"
  | "payments"
  | "invoices"
  | "utilities"
  | "approvals"
  | "units"
  | "customers"
  | "reservations"
  | "leases"
  | "letters"
  | "moveout"
  | "reports"
  | "history"
  | "settings";

export type IconName =
  | "home"
  | "payments"
  | "invoice"
  | "meter"
  | "check"
  | "units"
  | "customers"
  | "calendar"
  | "lease"
  | "list"
  | "moveout"
  | "reports"
  | "history"
  | "settings";

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
      { page: "invoices", icon: "invoice" },
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
        tabs: ["reservations"],
      },
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
    items: [{ page: "units", icon: "units" }],
  },
  {
    label: ["Office", "ការិយាល័យ"],
    items: [
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
  utilities: ["Utilities", "ទឹកភ្លើង"],
  approvals: ["Waiting for approval", "រង់ចាំការអនុម័ត"],
  units: ["Units", "បន្ទប់"],
  customers: ["Customers", "អតិថិជន"],
  reservations: ["Reservations", "ការកក់ទុក"],
  leases: ["Leases", "កិច្ចសន្យាជួល"],
  letters: ["Letters", "លិខិត"],
  moveout: ["Move-out", "ការចាកចេញ"],
  reports: ["Reports", "របាយការណ៍"],
  history: ["History", "ប្រវត្តិ"],
  settings: ["Settings", "ការកំណត់"],
};

export const PAGE_IDS = Object.keys(PAGE_NAMES) as PageId[];

export function pageName(page: PageId, language: Language): string {
  return PAGE_NAMES[page][language === "en" ? 0 : 1];
}

export function menuItemName(item: MenuItem, language: Language): string {
  return item.label === undefined
    ? pageName(item.page, language)
    : item.label[language === "en" ? 0 : 1];
}

/** The menu item that holds a page, directly or as one of its tabs. */
export function menuItemFor(page: PageId): MenuItem {
  for (const group of MENU) {
    for (const item of group.items) {
      if (item.page === page || item.tabs?.includes(page) === true) return item;
    }
  }
  throw new Error(`Page ${page} is not in the menu`);
}

export function groupLabel(group: MenuGroup, language: Language): string {
  return group.label === null ? "" : group.label[language === "en" ? 0 : 1];
}

export function isPageId(value: string): value is PageId {
  return Object.prototype.hasOwnProperty.call(PAGE_NAMES, value);
}

/** The page named by an address such as "#/units"; Home for anything else. */
export function pageFromHash(hash: string): PageId {
  const name = hash.replace(/^#\/?/, "");
  return isPageId(name) ? name : "home";
}

export function hashForPage(page: PageId): string {
  return `#/${page}`;
}
