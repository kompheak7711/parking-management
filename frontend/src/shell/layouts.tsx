// UI v81 shared layouts (owner 08/11/2026 06:55): built once from design v81, then every page
// moves onto them. PageHeader (Back link on top; title, status badge and one-line summary on
// the left; the buttons on the right, with "Manager only" as text beside a button, never inside
// it), DetailLayout (two columns, about 60/40, one column under 1024 px), FormLayout (a grid of
// fields, two short fields per row on a desktop and one on a phone; the summary panel on the
// right stays in view while scrolling), CardGrid and ListLayout (the card rules of round 3 and
// the list page whose table scrolls while the top stays). Layout only: nothing here changes
// what a page saves.

import {
  type FormEvent,
  type ReactNode,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { PageHeadContext } from "./pageHead";

/** Whether this element sits in a shell page box, and whether that box is on screen. */
function boxState(node: HTMLElement | null): {
  inBox: boolean;
  shown: boolean;
} {
  const box = node?.closest<HTMLElement>(".shell-page") ?? null;
  return { inBox: box !== null, shown: box === null ? true : !box.hidden };
}

export function PageHeader({
  back,
  title,
  badge,
  summary,
  actions,
  numeric = false,
}: {
  /** The "Back to X" link, on its own line above the title. */
  back?: ReactNode;
  title: ReactNode;
  /** The status chip beside the title. */
  badge?: ReactNode;
  /** The one-line summary under the title. */
  summary?: ReactNode;
  /** The buttons on the right; a `RightNote` beside a button says who may use it. */
  actions?: ReactNode;
  /** A title with a number in it (a document number) uses the number font. */
  numeric?: boolean;
}) {
  const slots = useContext(PageHeadContext);
  const anchor = useRef<HTMLElement>(null);
  const [owner, setOwner] = useState(false);
  // While the page is on screen the shell draws no page title and no tab bar: this header is
  // the page's head. Looked at again after each page change (the shell's page box hides).
  useLayoutEffect(() => {
    const { inBox, shown } = boxState(anchor.current);
    const owns = inBox && shown;
    setOwner(owns);
    if (!owns) return;
    slots.ownHead(true);
    return () => {
      slots.ownHead(false);
    };
  }, [slots, slots.page]);
  return (
    <header className="ui-pagehead" ref={anchor}>
      {back}
      <div className="ui-pagehead-row">
        <div className="ui-pagehead-text">
          <div className="ui-hrow">
            <h1
              className={
                numeric ? "ui-pagehead-title ui-num" : "ui-pagehead-title"
              }
              data-record-title=""
              id={owner ? "page-title" : undefined}
            >
              {title}
            </h1>
            {badge}
          </div>
          {summary !== undefined && summary !== null && summary !== false && (
            <p className="ui-pagehead-sub">{summary}</p>
          )}
        </div>
        {actions !== undefined && actions !== null && actions !== false && (
          <div className="ui-actions ui-pagehead-actions">{actions}</div>
        )}
      </div>
    </header>
  );
}

/**
 * A page whose in-page tabs are its head (owner 13/11/2026 23:44, Utilities): the title is for
 * screen readers only, no sub-line shows, and the buttons a tab sends with PageHead sit at the
 * right end of the tab row. The children are the tab's content.
 */
export function TabHead({
  title,
  tabs,
  children,
}: {
  title: string;
  /** The tab links (a <nav>). */
  tabs: ReactNode;
  children: ReactNode;
}) {
  const slots = useContext(PageHeadContext);
  const anchor = useRef<HTMLDivElement>(null);
  const [owner, setOwner] = useState(false);
  const [actions, setActions] = useState<HTMLElement | null>(null);
  const [sub, setSub] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const { inBox, shown } = boxState(anchor.current);
    const owns = inBox && shown;
    setOwner(owns);
    if (!owns) return;
    slots.ownHead(true);
    return () => {
      slots.ownHead(false);
    };
  }, [slots, slots.page]);
  return (
    <>
      <div className="shell-head shell-head-tabbed" ref={anchor}>
        <h1 className="ui-sr" id={owner ? "page-title" : undefined}>
          {title}
        </h1>
        <div className="shell-head-sub" hidden ref={setSub} />
        {tabs}
        <div className="shell-head-actions" ref={setActions} />
      </div>
      <PageHeadContext value={{ ...slots, sub, actions }}>
        {children}
      </PageHeadContext>
    </>
  );
}

/** Plain text beside a button in the actions row, such as "Manager only"; never inside it. */
export function RightNote({ children }: { children: ReactNode }) {
  return <span className="ui-only">{children}</span>;
}

/** A record page: the main cards on the left (about 60%), the side cards on the right. */
export function DetailLayout({
  main,
  side,
}: {
  main: ReactNode;
  side: ReactNode;
}) {
  return (
    <div className="ui-detail">
      <div className="ui-stack">{main}</div>
      <div className="ui-stack ui-detail-side">{side}</div>
    </div>
  );
}

/**
 * A form page: the fields card on the left, the summary panel on the right, which stays in
 * view while the fields scroll. The whole page is one form, so Enter and the buttons work.
 */
export function FormLayout({
  main,
  side,
  onSubmit,
  className,
  label,
}: {
  main: ReactNode;
  side: ReactNode;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  className?: string;
  /** The form's name for a screen reader, when no title inside it names it. */
  label?: string;
}) {
  return (
    <form
      aria-label={label}
      className={
        className === undefined ? "ui-formlayout" : `ui-formlayout ${className}`
      }
      noValidate
      onSubmit={onSubmit}
    >
      <div className="ui-stack">{main}</div>
      <div className="ui-stack ui-formlayout-side">{side}</div>
    </form>
  );
}

/** The fields of a form card: two short fields per row on a desktop, one per row on a phone. */
export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className="ui-fields">{children}</div>;
}

/** A field that takes the whole row (a long text, a choice list, the buttons). */
export function FullRow({ children }: { children: ReactNode }) {
  return <div className="ui-span2">{children}</div>;
}

/**
 * The facts of a record in columns (design v81 .facts): a small label over each value, with an
 * optional note under it. As many columns as fit, one on a phone.
 */
export interface Fact {
  key: string;
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
}

export function FactList({ facts }: { facts: readonly Fact[] }) {
  return (
    <dl className="ui-factlist">
      {facts.map((fact) => (
        <div key={fact.key}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}</dd>
          {fact.note !== undefined &&
            fact.note !== null &&
            fact.note !== false && (
              <dd className="ui-factlist-note">{fact.note}</dd>
            )}
        </div>
      ))}
    </dl>
  );
}

/**
 * The number cards of a page (round 3): twelve columns balanced by the number of cards so no
 * card is alone in a row on a desktop; two by two on a phone. `tasks` is the Home Tasks row
 * (four in a row, two by two on a phone). `five` (owner 12/11/2026, Home) puts five cards in a
 * row from an iPad up; a narrower screen keeps the rules above. A `label` names the cards as one
 * group; `className` adds a page's own card rules (the Home cards, the Financial summary row).
 */
export function CardGrid({
  children,
  tasks = false,
  five = false,
  label,
  className,
}: {
  children: ReactNode;
  tasks?: boolean;
  five?: boolean;
  label?: string;
  className?: string;
}) {
  const classes = [
    "ui-kpis",
    tasks ? "ui-tasks" : "",
    five ? "ui-five" : "",
    className ?? "",
  ]
    .filter((name) => name !== "")
    .join(" ");
  return (
    <div
      aria-label={label}
      className={classes}
      role={label === undefined ? undefined : "group"}
    >
      {children}
    </div>
  );
}

/**
 * A list page's table card (round 3): the bar with the count and filters on top, then the
 * table, which scrolls in its own area on a desktop while the top of the page stays
 * (shell/tableFit.ts sets the height).
 */
export function ListLayout({
  bar,
  children,
  labelledBy,
}: {
  bar?: ReactNode;
  children: ReactNode;
  labelledBy?: string;
}) {
  return (
    <section aria-labelledby={labelledBy} className="ui-card pad0 ui-list">
      {bar}
      <div className="ui-tablewrap">{children}</div>
    </section>
  );
}
