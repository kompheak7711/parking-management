// The screens the check opens (UI v81). A screen is done only when it passes this check and
// its design-and-app sheet matches. The list grows one module per batch: the pilot (owner
// 08/11/2026) is Lease details and New Lease; then Home (with a Tasks card open) and the side
// menu (owner 08/11/2026 09:57: open, collapsed, and with its groups folded); then Payments
// (owner 12/11/2026 07:41): the list, Receive payment with a Customer chosen, and a Receipt.

export interface Screen {
  /** A short name for the report and the screenshot file. */
  name: string;
  /** The address after the sign-in. */
  hash: string;
  /** The recorded server answers (e2e/fixtures/<fixture>.har.json). */
  fixture: string;
  /** Text that shows once the screen has its data. */
  ready: string;
  /** What the device remembers before the screen opens (the menu's localStorage keys). */
  storage?: Readonly<Record<string, string>>;
  /** "menu": the ☰ button is pressed where it shows (phone, tablet), so the drawer is open. */
  open?: "menu";
  /** The moment the browser's clock shows, for a fixture made for one day. */
  clock?: string;
}

/** Every menu group folded (the keys of AppShell's chetana-navgrp). */
const ALL_GROUPS_FOLDED = JSON.stringify({
  operations: true,
  leasing: true,
  property: true,
  administration: true,
});

export const SCREENS: readonly Screen[] = [
  {
    name: "home",
    hash: "#/home",
    fixture: "home",
    ready: "Next: in",
  },
  {
    name: "home-tasks",
    hash: "#/home?tasks=later",
    fixture: "home",
    ready: "Next: in",
  },
  // The side menu: on a desktop beside Home; on a phone or tablet the drawer behind ☰.
  {
    name: "menu-open",
    hash: "#/home",
    fixture: "home",
    ready: "Next: in",
    open: "menu",
  },
  // "Collapse menu" (icons only) exists on wide screens only; the drawer ignores it.
  {
    name: "menu-collapsed",
    hash: "#/home",
    fixture: "home",
    ready: "Next: in",
    storage: { "chetana-rail": "1" },
    open: "menu",
  },
  {
    name: "menu-folded",
    hash: "#/home",
    fixture: "home",
    ready: "Next: in",
    storage: { "chetana-navgrp": ALL_GROUPS_FOLDED },
    open: "menu",
  },
  {
    name: "lease-details",
    hash: "#/leases/7510dfbf-1307-4e67-a858-88ea6fe623fa",
    fixture: "pilot",
    ready: "Lease · U206L0022",
  },
  {
    name: "new-lease",
    hash: "#/leases/new",
    fixture: "pilot",
    ready: "What will be billed",
  },
  // Module batch 2, Payments. The list of the month.
  {
    name: "payments",
    hash: "#/payments",
    fixture: "payments",
    ready: "RCP260018",
  },
  // Receive payment for one Customer: the Customer card and the riel rate card beside the form.
  {
    name: "receive-payment",
    hash: "#/payments/receive%3A194daec5-9868-44b6-9294-cc440c986c52",
    fixture: "payments",
    ready: "Unpaid Invoices",
  },
  // One Receipt: the sheet, with "Paid for", the Customer card and "Reprints" beside it.
  {
    name: "receipt",
    hash: "#/payments/receipt%3A154f56c5-df30-4dda-9c77-b3684b4c8cb9",
    fixture: "payments",
    ready: "Unpaid Invoices",
  },
  // Module batch 3, Invoices. The list of the month.
  {
    name: "invoices",
    hash: "#/invoices",
    fixture: "invoices",
    ready: "INV260015",
  },
  // One Invoice: the head with Back, the sheet, and the shared Customer card beside it.
  {
    name: "invoice",
    hash: "#/invoices/inv%3Aa546c656-1297-480b-9aad-bfd7b69bb39f",
    fixture: "invoices",
    ready: "All Invoices for",
  },
  // New Quotation: the shared page head with Back.
  {
    name: "new-quotation",
    hash: "#/quotations/new",
    fixture: "invoices",
    ready: "New Quotation",
  },
  // Module batch 4, Utilities. The readings list (before the reading day) with Import in the head.
  {
    name: "utilities",
    hash: "#/utilities",
    fixture: "utilities",
    ready: "Until then, this list shows the last readings",
  },
  // The Meters tab: Add meter in the head with "Manager only" beside it.
  {
    name: "meters",
    hash: "#/utilities/meters",
    fixture: "utilities",
    ready: "Electricity meters",
  },
  // One meter: Report broken and Replace meter, each with "Manager only" beside it.
  {
    name: "meter",
    hash: "#/utilities/meter%3A6319db9a-6b85-416e-8491-752ef8af91c4",
    fixture: "utilities",
    ready: "Replace meter",
  },
  // Approvals (round 15, 13/11/2026): one Refund of Customer Credit waits, with Review.
  {
    name: "approvals",
    hash: "#/approvals",
    fixture: "approvals",
    ready: "Mao Sophea",
  },
  // Reservations (module batch 6, 14/11/2026): the tab row is the head; on a phone each
  // Reservation is a card. Then one cancelled Reservation's page: one head, History with names.
  {
    name: "reservations",
    hash: "#/reservations",
    fixture: "reservations",
    ready: "U407",
    clock: "2026-11-13T19:30:00Z",
  },
  {
    name: "reservation",
    hash: "#/reservations/add41500-adb9-47e3-ba99-db0edb642e80",
    fixture: "reservations",
    ready: "By Kompheak",
    clock: "2026-11-13T19:30:00Z",
  },
  // Leasing batch (owner 13/11/2026, design FINAL): the Short stays Calendar as a booking chart
  // with the quick numbers and the Today panel. Made-up guests for 13/11/2026
  // (e2e/fixtures/shortstays.har.json).
  {
    name: "shortstays-calendar",
    hash: "#/shortstays",
    fixture: "shortstays",
    ready: "Chan Sophea",
    clock: "2026-11-13T03:00:00Z",
  },
  // Owner 13/11/2026: the Bookings list (search, cards on a phone) and Housekeeping (short rows,
  // late first, done and skipped folded), same made-up guests.
  {
    name: "shortstays-bookings",
    hash: "#/shortstays?tab=list",
    fixture: "shortstays",
    ready: "Ouk Sreyneang",
    clock: "2026-11-13T03:00:00Z",
  },
  {
    name: "shortstays-housekeeping",
    hash: "#/shortstays?tab=clean",
    fixture: "shortstays",
    ready: "Finished (2)",
    clock: "2026-11-13T03:00:00Z",
  },
  // Owner 14/11/2026 01:43: "check Viewing request". Made-up people (e2e/fixtures/viewing.har.json).
  {
    name: "viewing-requests",
    hash: "#/visitreqs",
    fixture: "viewing",
    ready: "VR260003",
    clock: "2026-11-13T03:00:00Z",
  },
  // DL-238 (owner 14/11/2026 "Yes, build all four"): Notices › Short-stay guest notices. Made-up
  // guests (e2e/fixtures/guestnotices.har.json).
  {
    name: "guest-notices",
    hash: "#/letters/short-stays",
    fixture: "guestnotices",
    ready: "Late check-out notice",
    clock: "2026-11-13T03:00:00Z",
  },
  // Administration review (owner 13/11/2026 "All"): the tab row is the head, the 11 Ledger tabs
  // slide in one row, tables are cards on a phone, the Telegram paper-copy lists show 5 rows,
  // Users and access › History lists the access changes. Made-up data from the cloud review app
  // (e2e/fixtures/administration.har.json).
  {
    name: "ledger-expense-requests",
    hash: "#/exreqs",
    fixture: "administration",
    ready: "Open requests and advances",
  },
  {
    name: "ledger-statements",
    hash: "#/statements",
    fixture: "administration",
    ready: "Margin: water (4040 less 6020)",
  },
  {
    name: "audit-log",
    hash: "#/history",
    fixture: "administration",
    ready: "Payment allocation posted",
  },
  // Telegram › Linked tenants is not in the list yet: it stacks several lists (Linked now,
  // Invoices, Receipts), which the two-tables rule refuses; splitting it is the owner's call.
  {
    name: "telegram-health",
    hash: "#/tghealth",
    fixture: "administration",
    ready: "Messages not sent yet",
  },
  {
    name: "access-users",
    hash: "#/access",
    fixture: "administration",
    ready: "Chea Sreyneang",
  },
  {
    name: "access-history",
    hash: "#/access?tab=history",
    fixture: "administration",
    ready: "One-time password given",
  },
  {
    name: "settings-business",
    hash: "#/settings/business",
    fixture: "administration",
    ready: "Payment Methods",
  },
];

/** The five sizes of the owner's rule (width × height). */
export const SIZES: readonly (readonly [number, number])[] = [
  [390, 844],
  [768, 1024],
  [1366, 768],
  [1440, 900],
  [1920, 1080],
];
