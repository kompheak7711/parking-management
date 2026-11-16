// UI v81 (owner 07/11/2026 07:55): record pages stay on one page. A long list on a record (History,
// Receipts) shows only the latest few, with a button to a full page of its own. The full page is
// the record's address with "?view=<name>", so the browser's Back and "Back to X" return to the
// record. Display only: nothing here reads or saves anything.

import { useEffect, useState, type ReactNode } from "react";

import type { Language } from "../signInText";
import { BackLink, beforeForward } from "./backNav";
import { Icon } from "./icons";
import type { PageId } from "./navigation";

const TEXT = {
  history_btn: ["History", "ប្រវត្តិ"], // new
  history_title: ["History · {0}", "ប្រវត្តិ · {0}"], // new
  latest: ["Latest {0} of {1}", "ចុងក្រោយ {0} ក្នុង {1}"], // new
  receipts_btn: ["All Receipts", "បង្កាន់ដៃទាំងអស់"], // new
  receipts_title: ["Receipts · {0}", "បង្កាន់ដៃ · {0}"], // new
  statement_btn: ["Full statement", "របាយការណ៍ពេញ"], // new
  balance_due: ["Balance due", "សមតុល្យត្រូវបង់"], // new
} as const;

export type RecordViewText = keyof typeof TEXT;

export function rvt(
  language: Language,
  key: RecordViewText,
  ...values: (string | number)[]
): string {
  let text: string = TEXT[key][language === "en" ? 0 : 1];
  values.forEach((value, index) => {
    text = text.replace(`{${String(index)}}`, String(value));
  });
  return text;
}

function viewOf(hash: string): string | null {
  const at = hash.indexOf("?");
  if (at < 0) return null;
  return new URLSearchParams(hash.slice(at + 1)).get("view");
}

/** The full-page view open on this record ("history", "receipts"), or null for the record. */
export function useHashView(): string | null {
  const [view, setView] = useState(() => viewOf(window.location.hash));
  useEffect(() => {
    const follow = () => {
      setView(viewOf(window.location.hash));
    };
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, []);
  return view;
}

/** Opens a full-page view of the record on screen, as a new step the browser's Back undoes. */
export function openRecordView(view: string): void {
  const hash = window.location.hash;
  const at = hash.indexOf("?");
  const base = at < 0 ? hash : hash.slice(0, at);
  beforeForward();
  window.location.hash = `${base.replace(/^#/, "")}?view=${encodeURIComponent(view)}`;
}

/** Keeps the latest `count` items of a list that is newest first. */
export function latestOf<T>(items: readonly T[], count = 5): readonly T[] {
  return items.slice(0, count);
}

/** "Latest 5 of 12" above a cut list; nothing when the whole list shows. */
export function LatestNote({
  language,
  shown,
  total,
}: {
  language: Language;
  shown: number;
  total: number;
}) {
  if (total <= shown) return null;
  return (
    <p className="ui-small ui-muted">{rvt(language, "latest", shown, total)}</p>
  );
}

/** The button under a cut list that opens its full page, with the full count. */
export function ViewAllButton({
  label,
  total,
  view,
  icon = "history",
}: {
  label: string;
  total?: number;
  view: string;
  icon?: "history" | "list" | "payments";
}) {
  return (
    <div className="ui-qa">
      <button
        className="ui-btn"
        onClick={() => {
          openRecordView(view);
        }}
        type="button"
      >
        <Icon name={icon} small />
        {label}
        {total !== undefined && (
          <span className="ui-num ui-muted"> ({total})</span>
        )}
      </button>
    </div>
  );
}

/** The full page behind a record button: Back to the record, a title and the whole list. */
export function RecordViewPage({
  language,
  parent,
  parentDetail,
  recordName,
  title,
  sub,
  children,
}: {
  language: Language;
  parent: PageId;
  parentDetail: string;
  recordName: string;
  title: string;
  sub?: string;
  children: ReactNode;
}) {
  return (
    <>
      <BackLink
        language={language}
        parent={parent}
        parentDetail={parentDetail}
        parentLabel={recordName}
      />
      <div className="ui-head">
        <div>
          <h2 data-record-title="">{title}</h2>
          {sub !== undefined && <p>{sub}</p>}
        </div>
      </div>
      <section className="ui-card">{children}</section>
    </>
  );
}
