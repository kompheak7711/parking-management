// UI v81 round 3: a list page's main table scrolls in its own area; the page top stays in place.

import { readFileSync } from "node:fs";

import { afterEach, describe, expect, it } from "vitest";

import {
  holdsFold,
  installTableFit,
  largeCardsLook,
  mainTableBox,
  plainRowsHeight,
  planFit,
  scrollKey,
} from "./tableFit";

afterEach(() => {
  document.body.innerHTML = "";
  document.body.className = "";
  window.history.replaceState(null, "", "#/");
  window.sessionStorage.clear();
});

const byId = (id: string): HTMLElement => {
  const found = document.getElementById(id);
  if (found === null) throw new Error(`No element ${id}`);
  return found;
};

const tick = () =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, 40);
  });

describe("tableFit", () => {
  it("TEST-FE-1916 plans the table area: on a desktop the page fits the screen and the table takes the rest (one-line cards under 1000px tall); a phone, a tablet or a too-small area lets the page scroll with stuck headings; a table wider than its box gets no stuck headings; the main table is the visible one with the most rows and a record page is left alone", async () => {
    // 1440 x 900: the table starts 300px down and 80px of the page sits under it.
    expect(
      planFit({
        width: 1440,
        height: 900,
        tableTop: 300,
        tableHeight: 1200,
        pageHeight: 1580,
        tableWider: false,
      }),
    ).toEqual({ mode: "fit", maxHeight: 520, short: true });
    expect(
      planFit({
        width: 1920,
        height: 1080,
        tableTop: 300,
        tableHeight: 1200,
        pageHeight: 1580,
        tableWider: false,
      }),
    ).toEqual({ mode: "fit", maxHeight: 700, short: false });
    // 1366 x 768 with 500px above the table: 188px would be left, under the 240px floor.
    expect(
      planFit({
        width: 1366,
        height: 768,
        tableTop: 500,
        tableHeight: 1200,
        pageHeight: 1780,
        tableWider: false,
      }),
    ).toEqual({ mode: "flow" });
    expect(
      planFit({
        width: 390,
        height: 844,
        tableTop: 300,
        tableHeight: 400,
        pageHeight: 800,
        tableWider: false,
      }),
    ).toEqual({ mode: "flow" });
    expect(
      planFit({
        width: 390,
        height: 844,
        tableTop: 300,
        tableHeight: 400,
        pageHeight: 800,
        tableWider: true,
      }),
    ).toEqual({ mode: "plain" });
    expect(
      planFit({
        width: 1024,
        height: 699,
        tableTop: 100,
        tableHeight: 400,
        pageHeight: 600,
        tableWider: false,
      }),
    ).toEqual({ mode: "flow" });

    expect(scrollKey("")).toBe("ui-tablefit:#/");
    expect(scrollKey("#/invoices?tab=open")).toBe(
      "ui-tablefit:#/invoices?tab=open",
    );

    document.body.innerHTML = `<main>
      <div class="ui-tablewrap" id="one"><table><tbody><tr><td>1</td></tr></tbody></table></div>
      <div class="ui-tablewrap" id="two"><table><tbody><tr><td>1</td></tr><tr><td>2</td></tr></tbody></table></div>
      <div role="dialog"><div class="ui-tablewrap" id="in-dialog"><table><tbody><tr><td>1</td></tr><tr><td>2</td></tr><tr><td>3</td></tr></tbody></table></div></div>
      <div class="ui-tablewrap" id="empty"><table><tbody></tbody></table></div>
    </main>`;
    window.history.replaceState(null, "", "#/invoices");
    expect(mainTableBox(document.body)?.id).toBe("two");
    window.history.replaceState(null, "", "#/invoices/inv-1");
    expect(mainTableBox(document.body)).toBeNull();

    // Installed: the main table gets its scrolling area (the test window counts as a desktop)
    // and the place it is scrolled to is kept for Back.
    window.history.replaceState(null, "", "#/invoices");
    window.sessionStorage.setItem(
      scrollKey("#/invoices"),
      JSON.stringify({ table: 0, page: 0 }),
    );
    const stop = installTableFit();
    await tick();
    const two = document.getElementById("two");
    expect(two?.classList.contains("ui-tscroll")).toBe(true);
    expect(two?.style.maxHeight).toBe(`${String(window.innerHeight)}px`);
    expect(document.body.classList.contains("ui-fit")).toBe(true);
    two?.dispatchEvent(new Event("scroll"));
    const kept: unknown = JSON.parse(
      window.sessionStorage.getItem(scrollKey("#/invoices")) ?? "null",
    );
    expect(kept).toEqual({ table: 0, page: 0 });
    stop();
    expect(two?.classList.contains("ui-tscroll")).toBe(false);
    expect(document.body.classList.contains("ui-fit")).toBe(false);
  });

  it("TEST-FE-1936 (owner 12/11/2026) a table whose card holds a history that folds open is not fitted, so the page scrolls as usual and the opened history has room; a history still folded shut is not a second table; a card with two tables that show is still one scrolling area", async () => {
    // A desktop that would fit the table: with a history in the card the page flows instead.
    const desktop = {
      width: 1440,
      height: 900,
      tableTop: 300,
      tableHeight: 1200,
      pageHeight: 1580,
    };
    expect(planFit({ ...desktop, tableWider: false })).toEqual({
      mode: "fit",
      maxHeight: 520,
      short: true,
    });
    expect(planFit({ ...desktop, tableWider: false, folds: true })).toEqual({
      mode: "flow",
    });
    expect(planFit({ ...desktop, tableWider: true, folds: true })).toEqual({
      mode: "plain",
    });

    const rows = (count: number) =>
      "<table><tbody>" +
      "<tr><td>1</td></tr>".repeat(count) +
      "</tbody></table>";
    // Settings › Monthly services: the Services table, and the rate history folded under it.
    document.body.innerHTML = `<main><section class="ui-card" id="card">
      <div class="ui-tablewrap" id="services">${rows(2)}</div>
      <details class="ui-hist"><summary>Rate history</summary>
        <div class="ui-tablewrap" id="history">${rows(5)}</div>
      </details>
    </section></main>`;
    window.history.replaceState(null, "", "#/settings/services");
    const card = byId("card");
    const services = byId("services");
    const history = byId("history");
    expect(holdsFold(services)).toBe(true);
    expect(holdsFold(card)).toBe(true);
    // Folded shut (a browser says the history does not show): the Services table is the main
    // table, not the card, however many rows the history has.
    history.checkVisibility = () => false;
    expect(mainTableBox(document.body)?.id).toBe("services");
    // Open: both tables show, so the card is the main box.
    history.checkVisibility = () => true;
    expect(mainTableBox(document.body)?.id).toBe("card");
    const stop = installTableFit();
    await tick();
    // Nothing is fitted: no scrolling area, no height, no fitted page spacing.
    expect(document.querySelector(".ui-tscroll")).toBeNull();
    expect(card.style.maxHeight).toBe("");
    expect(services.style.maxHeight).toBe("");
    expect(document.body.classList.contains("ui-fit")).toBe(false);
    stop();

    // The Business rules by group: two tables that show and no history. One scrolling area.
    document.body.innerHTML = `<main><section class="ui-card" id="rules">
      <div class="ui-tablewrap">${rows(1)}</div>
      <div class="ui-tablewrap" id="prices">${rows(2)}</div>
    </section></main>`;
    window.history.replaceState(null, "", "#/settings/business");
    const rules = byId("rules");
    expect(holdsFold(byId("prices"))).toBe(false);
    expect(mainTableBox(document.body)?.id).toBe("rules");
    const again = installTableFit();
    await tick();
    expect(rules.classList.contains("ui-tscroll")).toBe(true);
    expect(document.body.classList.contains("ui-fit")).toBe(true);
    again();
  });

  it("TEST-FE-1941 (owner 12/11/2026 11:03) on a large screen the number cards are as tall as the first screen allows: full height while six ordinary rows of the table show, then the middle look (name and number on one line, the note under them) while three show, and one line each only below that; the Payments cards are six in a row there", () => {
    // Headings 46px and rows 68px: six rows need 454px, three need 250px.
    const rowsHeight = (rows: number) => 46 + 68 * rows;
    // 2560 x 1300, the table starts 683px down with full cards: 617px for the table.
    expect(
      largeCardsLook({
        height: 1300,
        tableTopFull: 683,
        tableTopMid: () => {
          throw new Error("not measured when the full look fits");
        },
        rowsHeight,
      }),
    ).toBe("full");
    // 1920 x 1080: 381px with full cards is under six rows; the middle look leaves 487px.
    expect(
      largeCardsLook({
        height: 1080,
        tableTopFull: 699,
        tableTopMid: () => 593,
        rowsHeight,
      }),
    ).toBe("mid");
    // 1920 x 900: the middle look still shows three rows.
    expect(
      largeCardsLook({
        height: 900,
        tableTopFull: 699,
        tableTopMid: () => 593,
        rowsHeight,
      }),
    ).toBe("mid");
    // 1920 x 820: under three rows even with the middle look, so one line each.
    expect(
      largeCardsLook({
        height: 820,
        tableTopFull: 699,
        tableTopMid: () => 593,
        rowsHeight,
      }),
    ).toBe("line");

    // An ordinary row is the table's shortest row (the test window draws no boxes: 0px each).
    document.body.innerHTML = `<div class="ui-tablewrap" id="list"><table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr><tr><td>2</td></tr></tbody></table></div>
      <div class="ui-tablewrap" id="none"><table><tbody></tbody></table></div>`;
    expect(plainRowsHeight(byId("list"), 3)).toBe(0);
    expect(plainRowsHeight(byId("none"), 3)).toBe(0);

    // The looks come from the stylesheet.
    const css = readFileSync("src/shell/screens.css", "utf8");
    const block = (start: string) => {
      const from = css.indexOf(start);
      if (from < 0) throw new Error(`No block ${start}`);
      return css.slice(from, css.indexOf("\n}\n", from));
    };
    // Owner 16/11/2026: the Payments cards are five in a row like every row of cards.
    expect(css).not.toContain(".ui-kpis.ui-kpis-pay {");
    const mid = block("\nbody.ui-fit.ui-mid .ui-kpis:not(.ui-tasks) .ui-kpi {");
    expect(mid).toContain("grid-template-columns: minmax(0, 1fr) auto;");
    // The note stays in the middle look, under the name and the number.
    const note = block(
      "\nbody.ui-fit.ui-mid .ui-kpis:not(.ui-tasks) .ui-kpi .ui-kpi-note {",
    );
    expect(note).toContain("grid-column: 1 / -1;");
    expect(note).not.toContain("display: none");
  });
});
