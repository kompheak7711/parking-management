// V1-058 R2: small pieces the rebuilt screens share (mock-up app.css: chip, kpi, dialog).

import {
  type CSSProperties,
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { Icon, type ShellIcon } from "./icons";

export type Tone = "ok" | "warn" | "err" | "info" | "neutral";

export function Chip({
  tone,
  icon,
  children,
}: {
  tone: Tone;
  icon?: ShellIcon;
  children: ReactNode;
}) {
  return (
    <span className={`ui-chip ${tone}`}>
      {icon !== undefined && <Icon name={icon} small />}
      {children}
    </span>
  );
}

/** A count card that filters a list; pressed while its filter is on. */
export function CountCard({
  icon,
  tone,
  label,
  value,
  note,
  pressed,
  onPress,
  valueText,
  top = true,
}: {
  icon: ShellIcon;
  tone: Tone | "brand" | "none";
  label: string;
  value: number;
  /** A short line under the number; left out when the card name says enough. */
  note?: string;
  pressed: boolean;
  onPress: () => void;
  /** How the value is written, such as "$1,250.00"; the plain number by default. */
  valueText?: string;
  /** The number at the top right, beside the name, as on the Home cards (owner 16/11/2026: on
   * every card). False keeps the older look with the number under the name. */
  top?: boolean;
}) {
  const shown = valueText ?? String(value);
  const hasNote = note !== undefined && note !== "";
  const name = (
    <span className="ui-kpi-label">
      <span className="ui-kpi-icon">
        <Icon name={icon} small />
      </span>
      {top ? <span>{label}</span> : label}
    </span>
  );
  const number = <span className="ui-kpi-value ui-num">{shown}</span>;
  return (
    <button
      aria-label={
        hasNote ? `${label}: ${shown}. ${note}` : `${label}: ${shown}.`
      }
      aria-pressed={pressed}
      className={`ui-kpi${top ? " ui-kpi-top" : ""}${top && valueText !== undefined ? " ui-kpi-amount" : ""} ${value === 0 ? "none" : tone}`}
      onClick={onPress}
      type="button"
    >
      {top ? (
        <span className="ui-kpi-head">
          {name}
          {number}
        </span>
      ) : (
        <>
          {name}
          {number}
        </>
      )}
      {hasNote && <span className="ui-kpi-note">{note}</span>}
    </button>
  );
}

/**
 * A dialog over the page. With `onSubmit` its body is a form with Cancel and a submit button;
 * without it there is one button that closes it. Escape closes it too.
 */
export function Dialog({
  title,
  children,
  onClose,
  onSubmit,
  submitLabel,
  closeLabel,
  busy = false,
  wide = false,
  actions,
  noButtons = false,
  onEscape,
  confirmDiscard = false,
  drawer = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  submitLabel?: string;
  closeLabel: string;
  busy?: boolean;
  /** Up to 820px, for a table with many columns. */
  wide?: boolean;
  /** More buttons after Close, for a dialog without a form (such as Reject and Confirm). */
  actions?: ReactNode;
  /** V1-060 B6: the content brings its own buttons (an embedded form such as Add Customer). */
  noButtons?: boolean;
  /** V1-060 B7: what Escape does when it is not the same as Close. */
  onEscape?: () => void;
  /**
   * UI v81 (B2): ask "Discard your changes?" before typed changes are lost. Only for a plain Add
   * or Edit form whose Close just closes; money windows keep their own close rules (DL-112).
   */
  confirmDiscard?: boolean;
  /** Leasing batch (owner 13/11/2026): a side panel that is not a form also opens from the right. */
  drawer?: boolean;
}) {
  const headingId = useId();
  const box = useRef<HTMLDivElement>(null);
  // UI v81 (B2): a form (Add or Edit) opens as a drawer and asks before its changes are lost.
  const isForm = onSubmit !== undefined;
  const [dirty, setDirty] = useState(false);
  const [asking, setAsking] = useState(false);
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  const guarded = (action: () => void) => () => {
    if (isForm && confirmDiscard && dirtyRef.current) setAsking(true);
    else action();
  };
  const close = useRef(guarded(onEscape ?? onClose));
  const working = useRef(busy);
  useEffect(() => {
    close.current = guarded(onEscape ?? onClose);
    working.current = busy;
  });
  useDrawerHistory(isForm, () => {
    close.current();
  });

  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusable = () =>
      Array.from(
        box.current?.querySelectorAll<HTMLElement>(
          "input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])",
        ) ?? [],
      ).filter(
        (element) =>
          !(
            element instanceof HTMLInputElement &&
            element.type === "radio" &&
            !element.checked &&
            box.current?.querySelector(
              `input[type="radio"][name="${element.name}"]:checked`,
            ) != null
          ),
      );
    focusable()[0]?.focus();
    function onKey(event: KeyboardEvent) {
      // Escape works like Cancel, so not while a save is running. V1-060 B7: a held key counts
      // once.
      if (event.key === "Escape" && !event.repeat && !working.current)
        close.current();
      // Tab stays inside the dialog.
      if (event.key === "Tab") {
        const items = focusable();
        const first = items[0];
        const last = items[items.length - 1];
        if (first === undefined || last === undefined) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener?.isConnected === true) opener.focus();
    };
  }, []);

  const buttons = (
    <div className="ui-dlg-buttons">
      <button
        className="ui-btn"
        disabled={busy}
        onClick={guarded(onClose)}
        type="button"
      >
        {closeLabel}
      </button>
      {actions}
      {onSubmit !== undefined && (
        <button className="ui-btn primary" disabled={busy} type="submit">
          {submitLabel}
        </button>
      )}
    </div>
  );
  return (
    <div
      className={
        isForm || drawer ? "ui-dlg-back ui-drawer-back" : "ui-dlg-back"
      }
    >
      <div
        aria-labelledby={headingId}
        aria-modal="true"
        className={
          (wide ? "ui-dlg wide" : "ui-dlg") +
          (isForm || drawer ? " ui-drawer" : "")
        }
        ref={box}
        role="dialog"
      >
        <h2 id={headingId}>{title}</h2>
        {asking && (
          <DiscardAsk
            onDiscard={() => {
              setAsking(false);
              setDirty(false);
              dirtyRef.current = false;
              (onEscape ?? onClose)();
            }}
            onKeep={() => {
              setAsking(false);
            }}
          />
        )}
        {onSubmit === undefined ? (
          <>
            {children}
            {!noButtons && buttons}
          </>
        ) : (
          <form
            className="ui-form"
            noValidate
            onChange={() => {
              setDirty(true);
            }}
            onInput={() => {
              setDirty(true);
            }}
            onSubmit={onSubmit}
          >
            {children}
            {buttons}
          </form>
        )}
      </div>
    </div>
  );
}

const SHARED_TEXT = {
  discard_q: ["Discard your changes?", "បោះបង់ការផ្លាស់ប្តូររបស់អ្នក?"], // new
  discard_keep: ["Keep editing", "បន្តកែ"], // new
  discard_go: ["Discard", "បោះបង់"], // new
} as const;

function sharedText(key: keyof typeof SHARED_TEXT): string {
  return SHARED_TEXT[key][document.documentElement.lang === "km" ? 1 : 0];
}

/** UI v81 (B2): the question a form asks before its typed changes are thrown away. */
function DiscardAsk({
  onDiscard,
  onKeep,
}: {
  onDiscard: () => void;
  onKeep: () => void;
}) {
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    keep.current?.focus();
  }, []);
  return (
    <div className="ui-discard" role="alert">
      <p>{sharedText("discard_q")}</p>
      <button className="ui-btn" onClick={onKeep} ref={keep} type="button">
        {sharedText("discard_keep")}
      </button>
      <button className="ui-btn danger" onClick={onDiscard} type="button">
        {sharedText("discard_go")}
      </button>
    </div>
  );
}

/**
 * UI v81 (B3): on a phone a drawer is one step of the browser history, so the phone's Back
 * closes the drawer first. Off on wider screens and where the browser cannot tell the width.
 */
function useDrawerHistory(active: boolean, requestClose: () => void): void {
  const request = useRef(requestClose);
  request.current = requestClose;
  useEffect(() => {
    if (!active || typeof window.matchMedia !== "function") return;
    if (!window.matchMedia("(max-width: 640px)").matches) return;
    const mark = `drawer-${Math.random().toString(36).slice(2)}`;
    const base: unknown = window.history.state;
    const baseObject = typeof base === "object" && base !== null ? base : {};
    window.history.pushState({ ...baseObject, v81Drawer: mark }, "");
    function onPop() {
      const now: unknown = window.history.state;
      const open =
        typeof now === "object" &&
        now !== null &&
        (now as { v81Drawer?: string }).v81Drawer === mark;
      if (open) return;
      // Back was pressed: put the step back and let the form decide (it may ask first).
      window.history.pushState({ ...baseObject, v81Drawer: mark }, "");
      request.current();
    }
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      const now: unknown = window.history.state;
      if (
        typeof now === "object" &&
        now !== null &&
        (now as { v81Drawer?: string }).v81Drawer === mark
      )
        window.history.back();
    };
  }, [active]);
}

/** UI v81 (B2): one sub-tab of a page. */
export interface SubTab {
  id: string;
  label: string;
  /** The count badge (rows in that table); left out when unknown. */
  count?: number;
}

/**
 * UI v81 (B2): the sub-tab row. Pills on a wide screen, one scrolling row on a phone. The chosen
 * sub-tab is kept in the address ("?tab=") without a new history step. Arrow keys, Home and End
 * move between sub-tabs (WAI-ARIA tabs).
 */
export function SubTabs({
  tabs,
  current,
  onChange,
  label,
  idPrefix = "subtab",
}: {
  tabs: readonly SubTab[];
  current: string;
  onChange: (id: string) => void;
  label: string;
  idPrefix?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const pick = (id: string) => {
    onChange(id);
    try {
      const hash = window.location.hash;
      const at = hash.indexOf("?");
      const base = at < 0 ? hash : hash.slice(0, at);
      window.history.replaceState(
        window.history.state,
        "",
        `${base}?tab=${encodeURIComponent(id)}`,
      );
      // UI v81 side menu: the menu's sub-items follow the address, so tell them about it (a
      // replaced address fires no hashchange of its own). Only when the page is in the address
      // (a screen test may draw the tabs without one).
      if (base.startsWith("#"))
        window.dispatchEvent(new HashChangeEvent("hashchange"));
    } catch {
      // The sub-tab still changes; only the address is not updated.
    }
  };
  function onKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex((tab) => tab.id === current);
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % tabs.length
        : event.key === "ArrowLeft"
          ? (index - 1 + tabs.length) % tabs.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? tabs.length - 1
              : -1;
    const tab = tabs[next];
    if (next < 0 || tab === undefined) return;
    event.preventDefault();
    pick(tab.id);
    refs.current[next]?.focus();
  }
  if (tabs.length < 2) return null;
  return (
    <div
      aria-label={label}
      className="ui-subtabs"
      onKeyDown={onKey}
      role="tablist"
    >
      {tabs.map((tab, index) => (
        <button
          aria-controls={`${idPrefix}-panel-${tab.id}`}
          aria-selected={tab.id === current}
          id={`${idPrefix}-${tab.id}`}
          key={tab.id}
          onClick={() => {
            pick(tab.id);
          }}
          ref={(element) => {
            refs.current[index] = element;
          }}
          role="tab"
          tabIndex={tab.id === current ? 0 : -1}
          type="button"
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="ui-subtab-count ui-num">{tab.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/**
 * UI v81 (B2): the panel that belongs to a sub-tab. Its parts keep the normal space between them
 * (owner 12/11/2026: the cards on Approvals touched each other).
 */
export function SubTabPanel({
  id,
  idPrefix = "subtab",
  children,
}: {
  id: string;
  idPrefix?: string;
  children: ReactNode;
}) {
  return (
    <div
      aria-labelledby={`${idPrefix}-${id}`}
      className="ui-stack"
      id={`${idPrefix}-panel-${id}`}
      role="tabpanel"
      tabIndex={0}
    >
      {children}
    </div>
  );
}

/**
 * UI v81 round 4 (owner 08/11/2026): the sub-tab shown, from "?tab=" in the address, following
 * it when the address changes (the menu's sub-items link to "#/page?tab=<id>"). `set` changes it
 * from the sub-tab row (which writes the address itself).
 */
export function useSubTab<T extends string>(
  ids: readonly T[],
  fallback: T,
): [T, (next: T) => void] {
  const read = () => subTabFromAddress(ids, fallback) as T;
  const [tab, setTab] = useState<T>(read);
  const key = ids.join("|");
  useEffect(() => {
    const follow = () => {
      setTab(subTabFromAddress(ids, fallback) as T);
    };
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, [key, fallback]);
  return [tab, setTab];
}

/** UI v81 (B2): the sub-tab in the address when the page opens, if it is one of `ids`. */
export function subTabFromAddress(
  ids: readonly string[],
  fallback: string,
): string {
  const hash = window.location.hash;
  const at = hash.indexOf("?");
  if (at < 0) return fallback;
  const tab = new URLSearchParams(hash.slice(at + 1)).get("tab");
  return tab !== null && ids.includes(tab) ? tab : fallback;
}

/** UI v81 (B2): a panel's title, one line that says what it holds, and its "+ Add" button. */
export function PanelHeader({
  title,
  description,
  addLabel,
  onAdd,
  headingId,
  actions,
}: {
  title: string;
  description?: string;
  addLabel?: string;
  onAdd?: () => void;
  headingId?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="ui-panel-head">
      <div>
        <h2 id={headingId}>{title}</h2>
        {description !== undefined && (
          <p className="ui-panel-sub">{description}</p>
        )}
      </div>
      {(onAdd !== undefined || actions !== undefined) && (
        <div className="ui-panel-actions">
          {actions}
          {onAdd !== undefined && (
            <button className="ui-btn primary" onClick={onAdd} type="button">
              <Icon name="plus" small />
              {addLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** UI v81 (B2): an empty list says what would be here, in one line, and offers the next step. */
export function EmptyState({
  title,
  line,
  action,
}: {
  title: string;
  line: string;
  action?: ReactNode;
}) {
  return (
    <div className="ui-empty-state">
      <p className="ui-empty-title">{title}</p>
      <p>{line}</p>
      {action}
    </div>
  );
}

/** UI v81 (B2): a status in words with its tone; one look for every status in the app. */
export function StatusBadge({
  tone,
  children,
  icon,
}: {
  tone: Tone;
  children: ReactNode;
  icon?: ShellIcon;
}) {
  return (
    <Chip icon={icon} tone={tone}>
      {children}
    </Chip>
  );
}

/** UI v81 (B2): the filter row above a table: search, filters and the column choice. */
export function FilterBar({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <div aria-label={label} className="ui-filters" role="group">
      {children}
    </div>
  );
}

export interface TableColumn<Row> {
  id: string;
  label: string;
  cell: (row: Row) => ReactNode;
  /** Numbers and money line up on the right. */
  right?: boolean;
  /** May the person hide it with the column choice? */
  optional?: boolean;
}

/** UI v81 (B2): the "Columns" choice, for tables with optional columns. */
export function ColumnToggle<Row>({
  columns,
  hidden,
  onChange,
  label,
}: {
  columns: readonly TableColumn<Row>[];
  hidden: readonly string[];
  onChange: (hidden: string[]) => void;
  label: string;
}) {
  const optional = columns.filter((column) => column.optional === true);
  if (optional.length === 0) return null;
  return (
    <details className="ui-coltoggle">
      <summary className="ui-btn">{label}</summary>
      <div className="ui-coltoggle-list">
        {optional.map((column) => (
          <label className="ui-check" key={column.id}>
            <input
              checked={!hidden.includes(column.id)}
              onChange={(event) => {
                onChange(
                  event.target.checked
                    ? hidden.filter((id) => id !== column.id)
                    : [...hidden, column.id],
                );
              }}
              type="checkbox"
            />
            <span>{column.label}</span>
          </label>
        ))}
      </div>
    </details>
  );
}

/** UI v81 (B2): a table with a header row, hidden columns and an empty state. */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  caption,
  hidden = [],
  empty,
}: {
  columns: readonly TableColumn<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  caption: string;
  hidden?: readonly string[];
  empty: ReactNode;
}) {
  const shown = columns.filter((column) => !hidden.includes(column.id));
  if (rows.length === 0) return <>{empty}</>;
  return (
    <div className="ui-tablewrap">
      <table className="ui-table">
        <caption className="ui-sr">{caption}</caption>
        <thead>
          <tr>
            {shown.map((column) => (
              <th
                className={column.right === true ? "r" : undefined}
                key={column.id}
                scope="col"
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {shown.map((column) => (
                <td
                  className={column.right === true ? "r" : undefined}
                  key={column.id}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** UI v81 (B2): a skeleton while a panel's data loads. */
export function Skeleton({
  lines = 3,
  label,
}: {
  lines?: number;
  label: string;
}) {
  return (
    <div
      aria-busy="true"
      aria-label={label}
      className="ui-skeleton"
      role="status"
    >
      {Array.from({ length: lines }, (_, index) => (
        <span className="ui-skeleton-line" key={index} />
      ))}
    </div>
  );
}

/**
 * Property fix 1 (owner 14/11/2026): a row's buttons in one small menu ("Change ▾"), so a table
 * row stays one line high. The list is drawn fixed on the screen under (or over) its button, so
 * a table box that scrolls never cuts it. It closes after a choice, a click outside, Escape, or
 * when the page scrolls.
 */
export function RowMenu({
  label,
  name,
  children,
}: {
  /** The button's word. */
  label: string;
  /** What the menu is for, for screen readers ("Change: Pillow"). */
  name: string;
  /** The menu's buttons. */
  children: ReactNode;
}) {
  const box = useRef<HTMLDetailsElement>(null);
  const [place, setPlace] = useState<CSSProperties | null>(null);
  const close = useCallback(() => {
    if (box.current !== null) box.current.open = false;
    setPlace(null);
  }, []);
  useEffect(() => {
    if (place === null) return;
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        box.current?.contains(event.target) !== true
      )
        close();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      close();
      box.current?.querySelector("summary")?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [place, close]);
  return (
    <details
      className="ui-rowmenu"
      onClick={(event) => {
        // A choice inside the list closes the menu; the dialog it opens takes over.
        if (
          event.target instanceof HTMLElement &&
          event.target.closest(".ui-rowmenu-list button") !== null
        )
          close();
      }}
      onToggle={(event) => {
        const details = event.currentTarget;
        if (!details.open) {
          setPlace(null);
          return;
        }
        const rect = details.querySelector("summary")?.getBoundingClientRect();
        if (rect === undefined) return;
        const right = Math.max(8, window.innerWidth - rect.right);
        setPlace(
          rect.bottom + 180 > window.innerHeight
            ? { right, bottom: window.innerHeight - rect.top + 4 }
            : { right, top: rect.bottom + 4 },
        );
      }}
      ref={box}
    >
      <summary aria-label={name} className="ui-btn">
        {label}
        <Icon name="chevron" small />
      </summary>
      {place !== null && (
        <div className="ui-rowmenu-list" style={place}>
          {children}
        </div>
      )}
    </details>
  );
}
