// UI v81 (B3, owner task 07/11/2026): one shared Back helper.
// - The Back link reads "Back to X", where X is the page the person came from.
// - It returns to that page with its tab, filters, sort, page number and scroll place.
// - When the record was opened directly (a bookmark or a typed address), Back opens the parent list.
// - The browser Back button does the same, because Back here is the browser's own Back.
// - Tabs and sub-tabs replace the address instead of adding a step (see openTab and SubTabs).
// Display only: nothing here changes what a page saves.

import { useEffect, useState } from "react";

import type { Language } from "../signInText";
import { Icon } from "./icons";
import { hashForPage, pageName, type PageId } from "./navigation";

const TEXT = {
  back_to: ["Back to {0}", "ត្រឡប់ទៅ {0}"], // new
} as const;

/** What the history entry remembers about the page that was left. */
interface Came {
  label: string;
  hash: string;
}
interface EntryState {
  v81Scroll?: number;
  v81Label?: string;
  v81From?: Came;
}

function state(): EntryState {
  const value: unknown = window.history.state;
  return typeof value === "object" && value !== null
    ? (value as EntryState)
    : {};
}

/** The name of the page on screen: the record heading when a record is open, else the page title. */
export function currentPageLabel(): string {
  const view = document.getElementById("shell-view");
  // Batch 6: other pages stay mounted but hidden, so only a record heading on show counts
  // (a hidden page's heading made Back read "Back to Home" on a Reservation opened from the list).
  const record = Array.from(
    view?.querySelectorAll<HTMLElement>("[data-record-title]") ?? [],
  ).find((element) => element.closest("[hidden]") === null);
  const title = record ?? document.getElementById("page-title");
  return (title?.textContent ?? "").trim();
}

/** Keeps the scroll place and name of the page being left in its own history entry. */
export function rememberHere(): void {
  try {
    window.history.replaceState(
      { ...state(), v81Scroll: window.scrollY, v81Label: currentPageLabel() },
      "",
    );
  } catch {
    // Some browsers limit how often the state may change; Back then still works without it.
  }
}

let leaving: Came | null = null;
let popping = false;
let lastHash = window.location.hash;

/** Call before the address moves forward to a new page (links and code). */
export function beforeForward(): void {
  rememberHere();
  leaving = { label: currentPageLabel(), hash: window.location.hash };
}

// Links: remember the page before the browser follows a "#/..." link.
document.addEventListener(
  "click",
  (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    const link =
      event.target instanceof Element
        ? event.target.closest<HTMLAnchorElement>('a[href^="#/"]')
        : null;
    if (link === null || link.target === "_blank") return;
    if (link.getAttribute("href") === window.location.hash) return;
    beforeForward();
  },
  true,
);
window.addEventListener("popstate", () => {
  // A drawer's own history step has the same address; only a real page change counts.
  if (window.location.hash !== lastHash) popping = true;
});
window.addEventListener("hashchange", () => {
  lastHash = window.location.hash;
  if (popping) {
    popping = false;
    const scroll = state().v81Scroll;
    if (typeof scroll === "number") restoreScroll(scroll);
    return;
  }
  if (leaving !== null && leaving.hash !== window.location.hash) {
    const from = leaving;
    try {
      window.history.replaceState({ ...state(), v81From: from }, "");
    } catch {
      // As above.
    }
  }
  leaving = null;
});

/** Pages draw after their data loads, so the scroll place is set again for a short while. */
function restoreScroll(top: number): void {
  let tries = 0;
  const step = () => {
    window.scrollTo(0, top);
    tries += 1;
    if (tries < 8 && Math.abs(window.scrollY - top) > 2)
      window.setTimeout(step, 80);
  };
  window.setTimeout(step, 0);
}

/** Where Back goes: the page the person came from, or else the parent list. */
export function backTarget(
  parent: PageId,
  language: Language,
  parentDetail?: string,
  parentLabel?: string,
): { label: string; fromHistory: boolean; hash: string } {
  const from = state().v81From;
  if (from !== undefined && from.label !== "")
    return { label: from.label, fromHistory: true, hash: from.hash };
  return {
    label: parentLabel ?? pageName(parent, language),
    fromHistory: false,
    hash: hashForPage(parent, parentDetail),
  };
}

export function backLabel(label: string, language: Language): string {
  return TEXT.back_to[language === "en" ? 0 : 1].replace("{0}", label);
}

/** Goes back like the browser Back button; on a direct open, replaces the address with the parent. */
export function goBack(parent: PageId, parentDetail?: string): void {
  if (state().v81From !== undefined) {
    window.history.back();
    return;
  }
  const target = hashForPage(parent, parentDetail);
  window.history.replaceState(null, "", target);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/**
 * The "Back to X" link at the top of a record page. `parent` is the list it belongs to, used
 * when the record was opened directly.
 */
export function BackLink({
  parent,
  parentDetail,
  parentLabel,
  language,
  onBack,
}: {
  parent: PageId;
  parentDetail?: string;
  /** The name of the parent when it is a tab or record rather than a menu page. */
  parentLabel?: string;
  language: Language;
  /** For a page drawn inside another (not its own address): what Back does there. */
  onBack?: () => void;
}) {
  const [target, setTarget] = useState(() =>
    backTarget(parent, language, parentDetail, parentLabel),
  );
  useEffect(() => {
    setTarget(backTarget(parent, language, parentDetail, parentLabel));
  }, [parent, language, parentDetail, parentLabel]);
  return (
    <button
      className="ui-crumb"
      onClick={() => {
        if (onBack !== undefined) onBack();
        else goBack(parent, parentDetail);
      }}
      type="button"
    >
      <Icon name="back" small />
      {backLabel(
        onBack !== undefined
          ? (parentLabel ?? pageName(parent, language))
          : target.label,
        language,
      )}
    </button>
  );
}

/**
 * A remembered value for a list page (filter, sort, page number, search), kept for this browser
 * tab only, so Back finds the list as it was left.
 */
export function useRemembered<T>(
  key: string,
  initial: T,
): [T, (value: T) => void] {
  const storageKey = `v81:${key}`;
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = (next: T) => {
    setValue(next);
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // Private mode or full storage: the value still works until the page is left.
    }
  };
  return [value, set];
}
