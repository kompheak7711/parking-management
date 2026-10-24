// V1-058 R1: each page has its own address ("#/units"), so Back, Forward and bookmarks work.

import { useEffect, useState } from "react";

import { hashForPage, pageFromHash, type PageId } from "./navigation";

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

/** Opens a page from code (not from a link), the same way the menu link does. */
export function openPageInAddress(page: PageId, replace = false): void {
  const target = hashForPage(page);
  if (window.location.hash === target) return;
  if (replace) window.history.replaceState(null, "", target);
  else window.history.pushState(null, "", target);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
