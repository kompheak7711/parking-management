// UI v81 round 3 (owner 07/11/2026 17:30): on a list page the table scrolls and the top stays in
// place.
//
// Owner 12/11/2026 11:03: on a large screen (1600px wide and up) the number cards are as tall as
// the first screen allows: full height, then the middle look (the name and the number on one
// line, the note under them), and one line each only when even that leaves fewer than three rows
// of the table (see largeCardsLook).
//
// On a screen at least 1024px wide and 700px tall the page fits the screen: the title, tabs,
// filters and number cards stay where they are and only the page's main table scrolls, in its own
// area that fills the rest of the screen, with its column headings stuck at the top of that area.
// "Load more" and footers under the table stay under the area. On a phone, a tablet or a short
// screen the page scrolls as usual and only the headings stick under the top bar, when the table
// is not wider than the screen (a browser cannot stick a heading across a box that scrolls
// sideways). Back returns to the same place in the table.
//
// The main table is the visible table with the most rows on the page; a record page (an address
// with a record, "#/invoices/<id>") and dialogs are left alone. Nothing here changes what a page
// shows: only sizes, classes and scroll positions.

import { detailFromHash, pageFromHash } from "./navigation";

export const FIT_MIN_WIDTH = 1024;
export const FIT_MIN_HEIGHT = 700;
/** Under this height the number cards take one line each, so eight table rows still show. */
export const SHORT_HEIGHT = 1000;
/** The table area is never smaller than this; a page that cannot give it scrolls as usual. */
export const MIN_TABLE_HEIGHT = 240;
/** Rows a desktop list should show; a tall screen that shows fewer takes the tighter look. */
export const MIN_ROWS = 8;
/**
 * A large screen (owner 12/11/2026 11:03, "why are the Payments cards one line even on a large
 * screen?"): from this width the window's height alone no longer decides. The number cards keep
 * their full height while the first screen still shows LARGE_FULL_ROWS ordinary rows of the
 * table. With fewer, the cards take the middle look (the name and the number on one line, the
 * note under them), and only when even that leaves fewer than LARGE_MIN_ROWS rows do they take
 * one line each.
 */
export const LARGE_WIDTH = 1600;
export const LARGE_FULL_ROWS = 6;
export const LARGE_MIN_ROWS = 3;

/** The look of the number cards: full height, the middle look, or one line each. */
export type CardsLook = "full" | "mid" | "line";

export interface LargeScreen {
  /** The height of the browser window. */
  height: number;
  /** The table's top edge from the top of the page with the cards at full height. */
  tableTopFull: number;
  /** The same with the cards in the middle look (measured only when it is needed). */
  tableTopMid: () => number;
  /** The height of the column headings and `rows` ordinary rows. */
  rowsHeight: (rows: number) => number;
}

/** The look of the number cards on a large screen, from what the first screen would show. */
export function largeCardsLook(screen: LargeScreen): CardsLook {
  if (screen.height - screen.tableTopFull >= screen.rowsHeight(LARGE_FULL_ROWS))
    return "full";
  if (screen.height - screen.tableTopMid() >= screen.rowsHeight(LARGE_MIN_ROWS))
    return "mid";
  return "line";
}

export interface FitMeasure {
  /** The screen (the browser window's inner size). */
  width: number;
  height: number;
  /** The table box's top edge from the top of the page, and its natural height. */
  tableTop: number;
  tableHeight: number;
  /** The whole page's height with the table at its natural height. */
  pageHeight: number;
  /** The table is wider than its box (it scrolls sideways). */
  tableWider: boolean;
  /**
   * The table's card holds a history that folds open (Settings › Monthly services). Such a page
   * scrolls as usual, so the opened history has room (owner 12/11/2026: in a fitted card the
   * history opened out of sight and the page did not scroll).
   */
  folds?: boolean;
}

export type FitPlan =
  | { mode: "fit"; maxHeight: number; short: boolean }
  | { mode: "flow" }
  | { mode: "plain" };

/** What to do with the main table, from the measurements. */
export function planFit(m: FitMeasure): FitPlan {
  const flowOrPlain: FitPlan = m.tableWider
    ? { mode: "plain" }
    : { mode: "flow" };
  if (m.folds === true || m.width < FIT_MIN_WIDTH || m.height < FIT_MIN_HEIGHT)
    return flowOrPlain;
  const below = m.pageHeight - (m.tableTop + m.tableHeight);
  const maxHeight = Math.floor(m.height - m.tableTop - below);
  if (maxHeight < MIN_TABLE_HEIGHT) return flowOrPlain;
  return { mode: "fit", maxHeight, short: m.height < SHORT_HEIGHT };
}

/** The key the scroll position of a page is kept under, for Back. */
/** The height of the column headings and the first `rows` rows of the table in `box`. */
export function rowsHeight(box: HTMLElement, rows: number): number {
  const head = box.querySelector<HTMLElement>("thead");
  const row = box.querySelector<HTMLElement>("tbody tr");
  if (row === null) return 0;
  return (head === null ? 0 : head.offsetHeight) + row.offsetHeight * rows;
}

/** The height of the column headings and `rows` rows as tall as the table's shortest row. */
export function plainRowsHeight(box: HTMLElement, rows: number): number {
  const head = box.querySelector<HTMLElement>("thead");
  const heights = Array.from(
    box.querySelectorAll<HTMLElement>("tbody tr"),
    (row) => row.offsetHeight,
  );
  if (heights.length === 0) return 0;
  return (head === null ? 0 : head.offsetHeight) + Math.min(...heights) * rows;
}

export function scrollKey(hash: string): string {
  return `ui-tablefit:${hash === "" ? "#/" : hash}`;
}

interface SavedScroll {
  table: number;
  page: number;
}

const isVisible = (element: HTMLElement) =>
  typeof element.checkVisibility === "function"
    ? element.checkVisibility()
    : true;

function readSaved(key: string): SavedScroll | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as SavedScroll).table === "number" &&
      typeof (parsed as SavedScroll).page === "number"
    )
      return parsed as SavedScroll;
  } catch {
    // No session storage: Back starts at the top, nothing else changes.
  }
  return null;
}

function writeSaved(key: string, value: SavedScroll): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // No session storage: nothing to keep.
  }
}

/** Operations pages whose number cards keep the tighter look with no table rows (owner
 *  13/11/2026). */
const CARDS_NO_ROWS: ReadonlySet<string> = new Set([
  "payments",
  "invoices",
  "quotations",
  "utilities",
  "approvals",
]);

/** A record page is open (its address names one record); the Meters tab is a list, not one. */
function detailOpen(): boolean {
  const hash = window.location.hash;
  const detail = detailFromHash(hash);
  return detail !== null && detail !== "meters";
}

/** The page's main table box, or null when the page has none to fit. */
export function mainTableBox(root: ParentNode): HTMLElement | null {
  // UI v81 round 4: a Settings address names a tab ("#/settings/business"), not a record.
  const hash = window.location.hash;
  if (pageFromHash(hash) !== "settings" && detailFromHash(hash) !== null)
    return null;
  const boxes = Array.from(
    root.querySelectorAll<HTMLElement>(".ui-tablewrap"),
  ).filter(
    (box) =>
      box.closest("[role='dialog'], dialog, [hidden]") === null &&
      box.querySelector("tbody tr") !== null &&
      isVisible(box),
  );
  if (boxes.length === 0) return null;
  const rows = (box: HTMLElement) => box.querySelectorAll("tbody tr").length;
  const best = boxes.reduce((best, box) =>
    rows(box) > rows(best) ? box : best,
  );
  // UI v81 round 4 (owner 08/11/2026): a card that holds several tables (the Business rules by
  // group) scrolls as one area, so every group stays reachable. Only tables that show count: a
  // history still folded shut is not a second table.
  const card = best.closest<HTMLElement>(".ui-card");
  if (card !== null && boxes.filter((box) => card.contains(box)).length > 1)
    return card;
  return best;
}

/** The card of this table holds a history that folds open (`details.ui-hist`). */
export function holdsFold(box: HTMLElement): boolean {
  const history = box.closest(".ui-card")?.querySelector("details.ui-hist");
  return history != null;
}

/**
 * Starts fitting the page's main table and keeping its scroll position; returns the function
 * that stops it. Call it once, from the shell.
 */
export function installTableFit(): () => void {
  const root = document.body;
  let current: HTMLElement | null = null;
  /** The page whose list was last fitted (its cards keep their look while the list is empty). */
  let fittedPage: string | null = null;
  let queued = 0;
  let key = scrollKey(window.location.hash);
  let pending = readSaved(key);
  let restoreTimer = 0;

  function clear(box: HTMLElement | null) {
    if (box === null) return;
    box.classList.remove("ui-tscroll", "ui-tflow");
    box.style.maxHeight = "";
  }

  function save() {
    // Until Back has put the page where it was, a scroll made by the shell is not the person's.
    if (pending !== null) return;
    writeSaved(key, {
      table: current === null ? 0 : current.scrollTop,
      page: window.scrollY,
    });
  }

  function restore(box: HTMLElement, plan: FitPlan) {
    if (pending === null) return;
    const wanted = pending;
    const tableReady =
      plan.mode !== "fit" ||
      box.scrollHeight - box.clientHeight >= wanted.table;
    const pageReady =
      document.documentElement.scrollHeight - window.innerHeight >= wanted.page;
    if (!tableReady || !pageReady) return;
    if (plan.mode === "fit") box.scrollTop = wanted.table;
    window.scrollTo(0, wanted.page);
    pending = null;
    window.clearTimeout(restoreTimer);
  }

  function apply() {
    queued = 0;
    const topbar = document.querySelector<HTMLElement>(".shell-topbar");
    root.style.setProperty(
      "--ui-top",
      `${String(topbar === null ? 0 : topbar.offsetHeight)}px`,
    );
    const box = mainTableBox(root);
    if (box !== current) {
      clear(current);
      current = box;
    }
    const listPage = window.location.hash.split("?")[0] ?? "";
    if (box === null) {
      // Owner 13/11/2026: a number card that filters the list (Payments › Late-payment, Utilities,
      // Other charges) can leave the list empty. The cards then keep the look they had, so they
      // do not grow.
      if (listPage === fittedPage) return;
      // Owner 13/11/2026 23:44 (iPad): an Operations list that has no table rows at all (nothing
      // waiting in Approvals, no Quotation in a card, the Meters tab) takes the same tighter
      // look of a fitting screen as a list with rows, so its cards are never the tall ones.
      const fitNoRows =
        CARDS_NO_ROWS.has(pageFromHash(window.location.hash)) &&
        !detailOpen() &&
        window.innerWidth >= FIT_MIN_WIDTH &&
        window.innerHeight >= FIT_MIN_HEIGHT;
      root.classList.toggle("ui-fit", fitNoRows);
      root.classList.remove("ui-mid");
      root.classList.toggle(
        "ui-short",
        fitNoRows &&
          window.innerWidth < LARGE_WIDTH &&
          window.innerHeight < SHORT_HEIGHT,
      );
      return;
    }
    fittedPage = listPage;
    const folds = holdsFold(box);
    const fitScreen =
      !folds &&
      window.innerWidth >= FIT_MIN_WIDTH &&
      window.innerHeight >= FIT_MIN_HEIGHT;
    const large = window.innerWidth >= LARGE_WIDTH;
    // Measure with the fitted spacing on, since it moves the table. A laptop under 1000px tall
    // starts with the tighter look; a large screen starts with its cards at full height.
    root.classList.toggle("ui-fit", fitScreen);
    root.classList.remove("ui-mid");
    root.classList.toggle(
      "ui-short",
      fitScreen && !large && window.innerHeight < SHORT_HEIGHT,
    );
    box.classList.remove("ui-tflow");
    box.classList.toggle("ui-tscroll", fitScreen);
    box.style.maxHeight = "";
    const measure = () => {
      const rect = box.getBoundingClientRect();
      return planFit({
        width: window.innerWidth,
        height: window.innerHeight,
        tableTop: rect.top + window.scrollY,
        tableHeight: box.offsetHeight,
        pageHeight: document.documentElement.scrollHeight,
        tableWider: box.scrollWidth > box.clientWidth + 1,
        folds,
      });
    };
    let plan = measure();
    if (fitScreen && large) {
      // Owner 12/11/2026 11:03: a large screen keeps its cards as tall as the first screen
      // allows (see largeCardsLook); then the page is measured again.
      const tableTop = () => box.getBoundingClientRect().top + window.scrollY;
      const look = largeCardsLook({
        height: window.innerHeight,
        tableTopFull: tableTop(),
        tableTopMid: () => {
          root.classList.add("ui-mid");
          return tableTop();
        },
        rowsHeight: (rows) => plainRowsHeight(box, rows),
      });
      root.classList.toggle("ui-mid", look === "mid");
      root.classList.toggle("ui-short", look === "line");
      if (look !== "full") plan = measure();
      // A table area that would hold fewer than four ordinary rows shows less than the page
      // scrolling as usual does (what sits under the table then leaves the first screen), so
      // the page scrolls and the headings stick.
      if (
        look !== "line" &&
        plan.mode === "fit" &&
        plan.maxHeight < plainRowsHeight(box, LARGE_MIN_ROWS + 1)
      )
        plan =
          box.scrollWidth > box.clientWidth + 1
            ? { mode: "plain" }
            : { mode: "flow" };
    } else if (
      // A tall laptop screen whose table area would still show fewer than MIN_ROWS rows (two
      // rows of cards, a tall head) takes the tighter look of a short screen too, then measures
      // again.
      plan.mode === "fit" &&
      !root.classList.contains("ui-short") &&
      plan.maxHeight < rowsHeight(box, MIN_ROWS)
    ) {
      root.classList.add("ui-short");
      plan = measure();
    }
    if (plan.mode === "fit") {
      box.style.maxHeight = `${String(plan.maxHeight)}px`;
      // A second look: whatever still runs past the screen comes off the table area.
      const over = document.documentElement.scrollHeight - window.innerHeight;
      if (over > 0 && plan.maxHeight - over >= MIN_TABLE_HEIGHT)
        box.style.maxHeight = `${String(plan.maxHeight - over)}px`;
    } else {
      // No room for a table area (tall blocks above the list): the page scrolls and the headings
      // stick under the top bar. A fitting screen keeps its tighter spacing.
      if (!fitScreen) root.classList.remove("ui-fit", "ui-mid", "ui-short");
      box.classList.remove("ui-tscroll");
      box.classList.toggle("ui-tflow", plan.mode === "flow");
    }
    restore(box, plan);
  }

  function queue() {
    if (queued !== 0) return;
    queued = window.requestAnimationFrame(apply);
  }

  function onHashChange() {
    key = scrollKey(window.location.hash);
    pending = readSaved(key);
    window.clearTimeout(restoreTimer);
    if (pending !== null) {
      // A page that never grows back to where it was (rows gone) starts at the top.
      restoreTimer = window.setTimeout(() => {
        pending = null;
      }, 3000);
    }
    queue();
  }

  function onScroll(event: Event) {
    if (event.target === document || event.target === current) save();
  }

  const observer = new MutationObserver(queue);
  observer.observe(root, { childList: true, subtree: true });
  window.addEventListener("resize", queue);
  window.addEventListener("hashchange", onHashChange);
  document.addEventListener("scroll", onScroll, true);
  // A history folding open or shut changes which tables show ("toggle" does not bubble).
  document.addEventListener("toggle", queue, true);
  if (pending !== null) {
    restoreTimer = window.setTimeout(() => {
      pending = null;
    }, 3000);
  }
  queue();
  return () => {
    observer.disconnect();
    window.removeEventListener("resize", queue);
    window.removeEventListener("hashchange", onHashChange);
    document.removeEventListener("scroll", onScroll, true);
    document.removeEventListener("toggle", queue, true);
    window.cancelAnimationFrame(queued);
    window.clearTimeout(restoreTimer);
    clear(current);
    root.classList.remove("ui-fit", "ui-mid", "ui-short");
  };
}
