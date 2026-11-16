// UI v81 (owner 08/11/2026 06:55, point 4): every screen in e2e/screens.ts at the five sizes.
// The check FAILS on: horizontal page overflow; a button, link or tab under 44 × 44 px; colour
// contrast under 4.5:1 (axe-core); cut-off text or numbers; a role badge inside a button; a
// card alone in a grid row on a desktop; two stacked tables; and (owner 08/11/2026 09:57) any
// visible text that is an internal ID or placeholder ("LEASE-" + hex, a UUID, "Primary Lease
// Customer"...). Owner 12/11/2026 10:47: a five-in-a-row card grid (Home) holds five cards in
// its first row from an iPad up, and on a wide screen the menu's colour fills its column to the
// bottom of the page. The side menu is checked with the page. The problems are listed in the
// failure message. A screenshot of each screen and size goes to e2e/results/shots.

import { mkdirSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { replay } from "./replay";
import { SCREENS, SIZES } from "./screens";

const SHOTS = join(import.meta.dirname, "results", "shots");

/** Runs in the page: the layout checks that need the drawn boxes. */
function audit(width: number): string[] {
  const desktop = width >= 1024;
  const problems: string[] = [];
  const view = document.getElementById("shell-view") ?? document.body;
  const nav = document.getElementById("shell-nav");
  const visible = (el: Element): boolean => {
    if (el.closest("[hidden]") !== null) return false;
    // A folded <details> (the "Earlier forms" under a page) still gives its content boxes in
    // Chromium, but nothing in it is drawn until it is opened; only its <summary> shows.
    const folded = el.closest("details:not([open])");
    if (folded !== null && el.closest("summary")?.parentElement !== folded)
      return false;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const box = el.getBoundingClientRect();
    // A 1 × 1 box is a heading for screen readers only (.ui-sr), not drawn text.
    return box.width > 1 && box.height > 1;
  };
  const describe = (el: Element): string => {
    const text = el.textContent.trim().replace(/\s+/g, " ").slice(0, 40);
    const cls = el.getAttribute("class");
    return `<${el.tagName.toLowerCase()}${cls ? ` class="${cls}"` : ""}> "${text}"`;
  };
  const round = (box: DOMRect) =>
    `${String(Math.round(box.width))}×${String(Math.round(box.height))}`;

  // 1. Horizontal page overflow.
  const pageWidth = Math.max(
    document.documentElement.scrollWidth,
    document.body.scrollWidth,
  );
  if (pageWidth > window.innerWidth + 1)
    problems.push(
      `horizontal overflow: the page is ${String(pageWidth)}px wide in a ${String(window.innerWidth)}px window`,
    );

  // The page and, where it is on screen, the side menu (UI v81 side menu, owner 08/11/2026).
  const roots = nav !== null && visible(nav) ? [view, nav] : [view];
  const all = <T extends Element>(selector: string): T[] =>
    roots.flatMap((root) => [...root.querySelectorAll<T>(selector)]);

  // 2. Buttons, links and tabs under 44 × 44 px (a checkbox or radio counts with its label).
  const targets = all<HTMLElement>(
    'a[href], button, [role="button"], [role="tab"], summary, input[type="checkbox"], input[type="radio"]',
  );
  for (const el of targets) {
    if (!visible(el)) continue;
    const measured =
      el instanceof HTMLInputElement ? (el.closest("label") ?? el) : el;
    const box = measured.getBoundingClientRect();
    if (box.width < 44 - 0.5 || box.height < 44 - 0.5)
      problems.push(`target under 44×44 (${round(box)}): ${describe(el)}`);
  }

  // 3. Cut-off text or numbers: text clipped inside a box that does not scroll, or a number
  //    that runs past its box.
  for (const el of all<HTMLElement>("*")) {
    if (!visible(el)) continue;
    const style = getComputedStyle(el);
    const clips = (value: string) => value === "hidden" || value === "clip";
    // A document sheet (an Invoice, a Receipt) is drawn scaled to its column (SheetFrame), so
    // its frame always holds a box of the paper's own width. It is cut off only when the sheet
    // as drawn runs past its frame.
    if (el.classList.contains("ui-sheetwrap")) {
      const sheet = el.querySelector(".ui-sheet");
      if (sheet !== null) {
        const drawn = sheet.getBoundingClientRect();
        const frame = el.getBoundingClientRect();
        if (drawn.right > frame.right + 1 || drawn.bottom > frame.bottom + 1)
          problems.push(
            `cut-off sheet in ${describe(el)} (drawn ${round(drawn)} in ${round(frame)})`,
          );
      }
      continue;
    }
    const clipped =
      (clips(style.overflowX) && el.scrollWidth > el.clientWidth + 1) ||
      (clips(style.overflowY) && el.scrollHeight > el.clientHeight + 1);
    if (clipped && el.textContent.trim() !== "")
      problems.push(
        `cut-off text in ${describe(el)} (${String(el.scrollWidth)}×${String(el.scrollHeight)} in ${String(el.clientWidth)}×${String(el.clientHeight)})`,
      );
    if (
      style.whiteSpace === "nowrap" &&
      el.children.length === 0 &&
      el.textContent.trim() !== ""
    ) {
      const parent = el.parentElement;
      // Administration review fix 2 (owner 13/11/2026): a row of tabs that slides sideways
      // holds tabs past its edge on purpose; they are reached by sliding the row.
      const slides =
        parent !== null &&
        /^(auto|scroll)$/.test(getComputedStyle(parent).overflowX) &&
        parent.scrollWidth > parent.clientWidth + 1;
      if (parent !== null && !slides) {
        const box = el.getBoundingClientRect();
        const outer = parent.getBoundingClientRect();
        if (box.right > outer.right + 1 || box.left < outer.left - 1)
          problems.push(
            `text runs past its box: ${describe(el)} in ${describe(parent)}`,
          );
      }
    }
  }

  // 4. A role badge inside a button.
  for (const el of all<HTMLElement>('button, a.ui-btn, [role="button"]')) {
    if (!visible(el)) continue;
    if (
      el.querySelector(".ui-badge, .ui-chip") !== null ||
      /\b(manager|owner)\b/i.test(el.textContent)
    )
      problems.push(`role badge inside a button: ${describe(el)}`);
  }

  // 5. A card alone in a grid row on a desktop.
  if (desktop) {
    const grids = new Set<HTMLElement>();
    for (const card of view.querySelectorAll<HTMLElement>(
      ".ui-card, .ui-kpi, .ui-tile, [class*='card']",
    )) {
      const parent = card.parentElement;
      if (parent !== null && visible(card)) grids.add(parent);
    }
    for (const grid of grids) {
      const cards = [...grid.children].filter(
        (child): child is HTMLElement =>
          child instanceof HTMLElement &&
          /\b(ui-card|ui-kpi|ui-tile)\b|card/.test(child.className) &&
          visible(child),
      );
      if (cards.length < 2) continue;
      const rows = new Map<number, number>();
      for (const card of cards) {
        const top = Math.round(card.getBoundingClientRect().top);
        rows.set(top, (rows.get(top) ?? 0) + 1);
      }
      const counts = [...rows.values()];
      if (counts.length > 1 && Math.max(...counts) > 1 && counts.includes(1))
        problems.push(
          `a card alone in a grid row: ${describe(grid)} (rows of ${counts.join(", ")})`,
        );
    }
  }

  // 5b. Owner 12/11/2026 10:47: five cards in a row from an iPad up (Home).
  if (width >= 700)
    for (const grid of view.querySelectorAll<HTMLElement>(".ui-kpis.ui-five")) {
      const cards = [...grid.children].filter(
        (child): child is HTMLElement =>
          child instanceof HTMLElement && visible(child),
      );
      const lead = cards[0];
      if (lead === undefined || cards.length < 5) continue;
      const top = Math.round(lead.getBoundingClientRect().top);
      const first = cards.filter(
        (card) => Math.round(card.getBoundingClientRect().top) === top,
      ).length;
      if (first !== 5)
        problems.push(
          `not five cards in the first row: ${describe(grid)} (${String(first)} of ${String(cards.length)})`,
        );
    }

  // 5c. Owner 12/11/2026 10:47: on a wide screen (the menu beside the page) the menu's colour
  //     fills its column to the bottom of the page, however long the page is.
  if (width > 1080) {
    const shell = document.querySelector<HTMLElement>(".shell");
    const menu = document.querySelector<HTMLElement>(".shell-nav");
    if (shell !== null && menu !== null) {
      const paint = getComputedStyle(shell);
      const colour = getComputedStyle(menu).backgroundColor;
      const column = menu.getBoundingClientRect().width;
      const bottom = shell.getBoundingClientRect().bottom + window.scrollY;
      if (
        !paint.backgroundImage.includes(colour) ||
        paint.backgroundSize !== `${String(column)}px 100%` ||
        bottom < document.documentElement.scrollHeight - 1
      )
        problems.push(
          `the menu's colour does not fill its column to the bottom of the page (${paint.backgroundImage} ${paint.backgroundSize}, column ${String(column)}px, shell ends at ${String(Math.round(bottom))} of ${String(document.documentElement.scrollHeight)})`,
        );
    }
  }

  // 6. Two stacked tables.
  const tables = [...view.querySelectorAll("table")]
    .filter(visible)
    .map((table) => table.getBoundingClientRect());
  for (let i = 0; i < tables.length; i += 1)
    for (let j = i + 1; j < tables.length; j += 1) {
      const a = tables[i];
      const b = tables[j];
      if (a === undefined || b === undefined) continue;
      const sideBySide = a.right <= b.left + 1 || b.right <= a.left + 1;
      if (!sideBySide)
        problems.push(`two stacked tables (${round(a)} and ${round(b)})`);
    }

  // 7. Internal IDs or placeholder text anywhere a person can read (owner 08/11/2026 09:57):
  //    "LEASE-0a96849c55e3", a UUID, a long hex key, "Primary Lease Customer"... The build id at
  //    the foot of the menu is the one hex a person may see.
  const internal = [
    /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i,
    /\b[A-Z]{2,8}-[0-9a-f]{6,}\b/,
    /\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{16,}\b/i,
    /\b(?:Primary Lease (?:Customer|Tenant)|Lease Service|Synthetic|Lorem ipsum|TODO|undefined|null|NaN|\[object Object\]|Test (?:Customer|Unit|Lease|Tenant|Property))\b/,
  ];
  const seen = new Set<string>();
  for (const root of roots) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (
      let node = walker.nextNode();
      node !== null;
      node = walker.nextNode()
    ) {
      const parent = node.parentElement;
      if (parent === null || !visible(parent)) continue;
      if (parent.closest(".shell-build, script, style") !== null) continue;
      const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
      if (text === "") continue;
      for (const pattern of internal) {
        const match = pattern.exec(text);
        if (match === null) continue;
        const key = `${match[0]}|${describe(parent)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        problems.push(
          `internal ID or placeholder text "${match[0]}" in ${describe(parent)}`,
        );
      }
    }
  }
  return problems;
}

async function contrast(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page })
    .include("#shell-view")
    .include("#shell-nav")
    .withRules(["color-contrast"])
    .analyze();
  return results.violations.flatMap((violation) =>
    violation.nodes.map(
      (node) =>
        `contrast under 4.5:1: ${node.target.join(" ")} — ${node.failureSummary?.split("\n")[1] ?? violation.help}`,
    ),
  );
}

test.beforeAll(() => {
  mkdirSync(SHOTS, { recursive: true });
});

for (const screen of SCREENS) {
  for (const [width, height] of SIZES) {
    test(`${screen.name} at ${String(width)}×${String(height)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height });
      await replay(page, screen.fixture);
      // A screen whose made-up data is for one day opens on that day.
      if (screen.clock !== undefined)
        await page.clock.setFixedTime(new Date(screen.clock));
      if (screen.storage !== undefined)
        await page.addInitScript((entries: Record<string, string>) => {
          for (const [key, value] of Object.entries(entries))
            window.localStorage.setItem(key, value);
        }, screen.storage);
      await page.goto(`/${screen.hash}`);
      await expect(page.getByText(screen.ready).first()).toBeVisible({
        timeout: 30_000,
      });
      if (screen.open === "menu") {
        // The ☰ button shows on a phone or tablet only; a desktop has the menu beside the page.
        const menuButton = page.getByRole("button", {
          name: "Menu",
          exact: true,
        });
        if (await menuButton.isVisible()) {
          await menuButton.click();
          await expect(
            page.getByRole("button", { name: "Close the menu", exact: true }),
          ).toBeVisible();
        }
      }
      // The pages draw their data in a few steps; let the last one settle.
      await page.waitForTimeout(600);
      await page.screenshot({
        path: join(
          SHOTS,
          `${screen.name}-${String(width)}x${String(height)}.png`,
        ),
        fullPage: true,
      });
      const problems = [
        ...(await page.evaluate(audit, width)),
        ...(await contrast(page)),
      ];
      expect(
        problems,
        `${screen.name} at ${String(width)}×${String(height)}:\n${problems.join("\n")}`,
      ).toEqual([]);
    });
  }
}
