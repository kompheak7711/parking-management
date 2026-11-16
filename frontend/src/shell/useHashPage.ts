// V1-058 R1: each page has its own address ("#/units"), so Back, Forward and bookmarks work.

import { useCallback, useEffect, useRef, useState } from "react";

// V1-061 Fix 3: its address listener goes first, so a money window can keep the page.
import "./leaveGuard";
import { beforeForward } from "./backNav";

import {
  detailFromHash,
  hashForPage,
  pageFromHash,
  queryFromHash,
  type PageId,
} from "./navigation";

export function useHashPage(): PageId {
  const [page, setPage] = useState<PageId>(() =>
    pageFromHash(window.location.hash),
  );
  useEffect(() => {
    function follow() {
      setPage(pageFromHash(window.location.hash));
    }
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, []);
  return page;
}

/**
 * V1-058 R2: the record the address opens inside `page` ("#/units/<id>"), or null when the
 * address names another page.
 */
export function useHashDetail(page: PageId): string | null {
  const read = () =>
    pageFromHash(window.location.hash) === page
      ? detailFromHash(window.location.hash)
      : null;
  const [detail, setDetail] = useState<string | null>(read);
  useEffect(() => {
    function follow() {
      setDetail(
        pageFromHash(window.location.hash) === page
          ? detailFromHash(window.location.hash)
          : null,
      );
    }
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, []);
  return detail;
}

/**
 * UI v81 round 11 (owner 12/11/2026: "check all card is link to correct place"): a Home card
 * opens the part of a page that the card counts. The part is a word in the address
 * ("#/invoices?show=overdue"). The list of `page` gives `apply`: it is called with that word when
 * the list opens under such an address, and again each time such an address is opened, so Back
 * from a record returns to the same part. The function it returns keeps a part the person then
 * chooses by hand in the address (null: the whole list), without a new history step.
 * Display only: nothing here reads or saves anything.
 */
export function useShowFromAddress(
  page: PageId,
  apply: (show: string, query: URLSearchParams) => void,
): (show: string | null, more?: Record<string, string>) => void {
  const latest = useRef(apply);
  useEffect(() => {
    latest.current = apply;
  });
  useEffect(() => {
    function follow() {
      const hash = window.location.hash;
      if (pageFromHash(hash) !== page || detailFromHash(hash) !== null) return;
      const at = hash.indexOf("?");
      if (at < 0) return;
      const query = new URLSearchParams(hash.slice(at + 1));
      const show = query.get("show");
      if (show !== null) latest.current(show, query);
    }
    follow();
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, [page]);
  return useCallback(
    (show: string | null, more?: Record<string, string>) => {
      const hash = window.location.hash;
      if (pageFromHash(hash) !== page || detailFromHash(hash) !== null) return;
      const query = new URLSearchParams(
        show === null ? (more ?? {}) : { show, ...more },
      ).toString();
      const target =
        query === "" ? hashForPage(page) : `${hashForPage(page)}?${query}`;
      if (target === hash) return;
      try {
        window.history.replaceState(window.history.state, "", target);
      } catch {
        // The part still changes on screen; only the address is not updated.
      }
    },
    [page],
  );
}

/**
 * UI v81 round 11: the "show" word in the address right now, when the address is the list of
 * `page` ("#/customers?show=birthdays" gives "birthdays"), else null. For a first state, so a
 * page that reads from the server on its chosen part reads once.
 */
export function showInAddress(page: PageId): string | null {
  const hash = window.location.hash;
  return pageFromHash(hash) === page && detailFromHash(hash) === null
    ? queryFromHash(hash, "show")
    : null;
}

/**
 * UI v81 round 11: the same word, followed as the address changes. For a part that shows only
 * while the address asks for it.
 */
export function useHashShow(page: PageId): string | null {
  const [show, setShow] = useState<string | null>(() => showInAddress(page));
  useEffect(() => {
    function follow() {
      setShow(showInAddress(page));
    }
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, [page]);
  return show;
}

/** The address of one part of a page ("#/units?show=vacant"), for a link. */
export function hashForShow(
  page: PageId,
  show: string,
  more?: Record<string, string>,
): string {
  return `${hashForPage(page)}?${new URLSearchParams({ show, ...more }).toString()}`;
}

/** Opens a page from code (not from a link), the same way the menu link does. */
export function openPageInAddress(
  page: PageId,
  replace = false,
  detail?: string,
): void {
  const target = hashForPage(page, detail);
  if (window.location.hash === target) return;
  if (replace) window.history.replaceState(null, "", target);
  else {
    // UI v81 (B3): the page being left is remembered, so "Back to X" can return to it.
    beforeForward();
    window.history.pushState(null, "", target);
  }
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
