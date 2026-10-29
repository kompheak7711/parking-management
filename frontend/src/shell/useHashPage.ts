// V1-058 R1: each page has its own address ("#/units"), so Back, Forward and bookmarks work.

import { useEffect, useState } from "react";

// V1-061 Fix 3: its address listener goes first, so a money window can keep the page.
import "./leaveGuard";

import {
  detailFromHash,
  hashForPage,
  pageFromHash,
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

/** Opens a page from code (not from a link), the same way the menu link does. */
export function openPageInAddress(
  page: PageId,
  replace = false,
  detail?: string,
): void {
  const target = hashForPage(page, detail);
  if (window.location.hash === target) return;
  if (replace) window.history.replaceState(null, "", target);
  else window.history.pushState(null, "", target);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
