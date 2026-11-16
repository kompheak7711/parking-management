// UI v81 round 2 (owner 07/11/2026): the design's page head is one row: the title with its
// sub-line on the left and the page's buttons on the right. The title is drawn by AppShell, so a
// page sends its sub-line and buttons into the shell's head through this context. Without the
// shell (tests) the row is drawn in the page. Only the page on screen fills the head: a page
// says so with `active`, or PageHead reads the page it sits in from the shell's page box.

import {
  Children,
  type ReactNode,
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

export interface PageHeadSlots {
  /** The page on screen (AppShell's page id); a change makes every head look again. */
  page: string | null;
  sub: HTMLElement | null;
  actions: HTMLElement | null;
  /** UI v81 shared layouts: a page's own PageHeader takes the head; the shell then draws no
   *  page title and no tab bar while that page is on screen. */
  ownHead: (owned: boolean) => void;
}

export const PageHeadContext = createContext<PageHeadSlots>({
  page: null,
  sub: null,
  actions: null,
  ownHead: () => undefined,
});

function present(node: ReactNode): boolean {
  return node !== undefined && node !== null && node !== false && node !== "";
}

export function PageHead({
  active,
  sub,
  actions,
  children,
}: {
  /** Whether the page is on screen; left out, PageHead finds out from the shell's page box. */
  active?: boolean;
  sub?: ReactNode;
  actions?: ReactNode;
  /** The row's content when sub and actions are not given: the first child goes under the
   *  title, the rest go beside it. */
  children?: ReactNode;
}) {
  const slots = useContext(PageHeadContext);
  const anchor = useRef<HTMLSpanElement>(null);
  // Found from the shell's page box around this head: whether there is one, and whether it is
  // on screen. Looked at after every draw, because the box's hidden mark changes with the page.
  const [box, setBox] = useState<{ inBox: boolean; shown: boolean } | null>(
    null,
  );
  useLayoutEffect(() => {
    if (active !== undefined) return;
    const found = anchor.current?.closest(".shell-page");
    const inBox = found instanceof HTMLElement;
    const next = { inBox, shown: inBox ? !found.hidden : true };
    setBox((previous) =>
      previous !== null &&
      previous.inBox === next.inBox &&
      previous.shown === next.shown
        ? previous
        : next,
    );
  });

  const parts = Children.toArray(children);
  const subNode = sub ?? parts[0];
  const actionNodes =
    actions ?? (parts.length > 1 ? parts.slice(1) : undefined);
  const subSlot = slots.sub;
  const actionSlot = slots.actions;
  const shown = active ?? (box === null ? null : box.shown);
  const inBox = active !== undefined || box?.inBox === true;
  const marker = active === undefined ? <span hidden ref={anchor} /> : null;

  if (shown === null) return marker;
  if (!shown) return marker;
  if (subSlot !== null && actionSlot !== null && inBox) {
    return (
      <>
        {marker}
        {present(subNode) && createPortal(subNode, subSlot)}
        {present(actionNodes) && createPortal(actionNodes, actionSlot)}
      </>
    );
  }
  return (
    <>
      {marker}
      <div className="ui-head">
        <div>{subNode}</div>
        {actionNodes}
      </div>
    </>
  );
}
