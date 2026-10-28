// V1-060 B6 (DL-107, owner 28/10/2026): every button looks like a button, never like a text box.
// A text box is Paper with a grey edge; a button has a light green fill, green words and a green
// edge, in light and dark, and its words stay readable (WCAG 2.2 AA).

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const shell = readFileSync("src/shell/shell.css", "utf8");
const screens = readFileSync("src/shell/screens.css", "utf8");

/** The declarations of the first rule written as "<selector> {". */
function rule(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`No rule ${selector}`);
  const open = css.indexOf("{", start);
  return css.slice(open + 1, css.indexOf("}", open));
}

function colours(block: string): (name: string) => string {
  const found = new Map(
    [...block.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-f]{6});/g)].map((match) => [
      match[1] ?? "",
      match[2] ?? "",
    ]),
  );
  return (name) => {
    const value = found.get(name);
    if (value === undefined) throw new Error(`No colour ${name}`);
    return value;
  };
}

function luminance(hex: string): number {
  const [red = 0, green = 0, blue = 0] = [1, 3, 5].map((at) => {
    const channel = parseInt(hex.slice(at, at + 2), 16) / 255;
    return channel <= 0.03928
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(first: string, second: string): number {
  const [light, dark] = [luminance(first), luminance(second)].sort(
    (left, right) => right - left,
  );
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05);
}

describe("Buttons", () => {
  it("TEST-FE-1076 every button looks like a button, never like a text box, in light and dark, and its words stay readable", () => {
    for (const colour of [
      colours(rule(shell, "\n:root")),
      colours(rule(shell, ':root:not([data-theme="light"])')),
    ]) {
      // A button's fill and edge are never a text box's.
      expect(colour("--btn-bg")).not.toBe(colour("--input"));
      expect(colour("--btn-bg")).not.toBe(colour("--surface"));
      expect(colour("--btn-edge")).not.toBe(colour("--border-strong"));
      // The words on a button, also under the pointer (4.5:1), and its edge on cards and on the
      // page (3:1); the chosen part of a switch is green with Paper words.
      expect(
        contrast(colour("--btn-text"), colour("--btn-bg")),
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrast(colour("--btn-text"), colour("--btn-hover")),
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrast(colour("--btn-edge"), colour("--surface")),
      ).toBeGreaterThanOrEqual(3);
      expect(
        contrast(colour("--btn-edge"), colour("--bg")),
      ).toBeGreaterThanOrEqual(3);
      expect(
        contrast(colour("--on-primary"), colour("--primary")),
      ).toBeGreaterThanOrEqual(4.5);
    }
    // Buttons, switches, the calendar button beside a date box, the calendar's month arrows and
    // the square icon buttons.
    for (const selector of [
      "\n.ui-btn",
      "\n.ui-seg",
      "\n.ui-date .ui-date-button",
      "\n.ui-cal-nav",
      "\n.ui-iconbtn",
    ]) {
      const block = rule(screens, selector);
      expect(block).toContain("background: var(--btn-bg);");
      expect(block).toContain("border: 1px solid var(--btn-edge);");
    }
    expect(rule(screens, "\n.ui-btn")).toContain("color: var(--btn-text);");
    // A button that opens a page keeps the button's words, not a page link's green.
    expect(
      rule(
        screens,
        "\n.shell-view a.ui-btn:not(.primary, .link, .danger, .ui-locked),\n.shell-view a.ui-iconbtn",
      ),
    ).toContain("color: var(--btn-text);");
    expect(rule(screens, '\n.ui-seg button[aria-pressed="true"]')).toContain(
      "background: var(--primary);",
    );
  });
  it("TEST-FE-1086 every drop-down keeps its drawn arrow: a rule that also styles a select sets only its background colour, and the arrow has room (V1-060 B7)", () => {
    const rules = (css: string) =>
      [
        ...css
          .replace(/\/\*[\s\S]*?\*\//g, "")
          .matchAll(/([^{}]+)\{([^{}]*)\}/g),
      ].map((match) => ({
        selector: match[1]?.trim() ?? "",
        body: match[2] ?? "",
      }));
    // shell.css loads after screens.css, so none of its select rules may set the whole
    // background (that would clear the drawn arrow).
    for (const { selector, body } of rules(shell))
      if (/\bselect\b/.test(selector))
        expect(body).not.toMatch(/(^|[\s;])background:/);
    // A select with a class or state is more specific than the arrow rule; it keeps it too.
    for (const { selector, body } of rules(screens))
      if (/\bselect[.[:]/.test(selector))
        expect(body).not.toMatch(/(^|[\s;])background:/);
    const arrow = rule(screens, "\n.shell-view select,\n.ui-dlg select");
    expect(arrow).toContain("background-image: url(");
    expect(arrow).toContain("padding-right: 36px;");
    expect(rule(screens, "\n.shell-view select.ui-sel")).toContain(
      "padding: 0 36px 0 12px;",
    );
  });
});
