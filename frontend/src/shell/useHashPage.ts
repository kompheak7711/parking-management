// V1-058 R1: each page has its own address ("#/units"), so Back, Forward and bookmarks work.

import { useEffect, useState } from "react";

import { pageFromHash, type PageId } from "./navigation";

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
