// UI v81 round 8 (owner 12/11/2026): the look of the sub-tab row. TEST-FE-1933.
//
// The test was written on the Approvals tabs. Since DL-222 (a short-stay damage charge needs no
// approval) the Approvals page has one view and no tabs, so the test draws the shared parts
// themselves, as Settings and Users and access use them.
import { readFileSync } from "node:fs";

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SubTabPanel, SubTabs } from "./ui";

afterEach(() => {
  cleanup();
});

describe("Sub-tabs (UI v81)", () => {
  it("TEST-FE-1933 (owner 12/11/2026) the sub-tabs are square, not round pills, with the count a plain number; the panel under them is a stack, so its cards, lists and notes keep the normal space between them", () => {
    render(
      <>
        <SubTabs
          current="rules"
          idPrefix="test-tab"
          label="Parts of Business"
          onChange={vi.fn()}
          tabs={[
            { id: "general", label: "General" },
            { id: "rules", label: "Business rules", count: 75 },
          ]}
        />
        <SubTabPanel id="rules" idPrefix="test-tab">
          <div className="ui-kpis">Cards</div>
          <section className="ui-card">List</section>
          <div className="ui-notice info">Note</div>
        </SubTabPanel>
      </>,
    );
    const row = screen.getByRole("tablist", { name: "Parts of Business" });
    expect(row).toHaveClass("ui-subtabs");
    expect(
      within(row)
        .getAllByRole("tab")
        .map((each) => each.textContent),
    ).toEqual(["General", "Business rules75"]);
    const chosenTab = within(row).getByRole("tab", { name: /Business rules/ });
    expect(chosenTab).toHaveAttribute("aria-selected", "true");
    expect(within(chosenTab).getByText("75")).toHaveClass(
      "ui-subtab-count",
      "ui-num",
    );

    // Each part is the panel's own child, so the stack spaces them.
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveClass("ui-stack");
    expect(Array.from(panel.children).map((part) => part.className)).toEqual([
      "ui-kpis",
      "ui-card",
      "ui-notice info",
    ]);

    // The look comes from the stylesheet: a tab has square corners inside one joined box with
    // 8px corners (the Payments filter row), the chosen tab is tinted and underlined, never a
    // filled pill, and on a page the page's own space follows the tabs and spaces the panel.
    const css = readFileSync("src/shell/screens.css", "utf8");
    const rule = (selector: string) => {
      const start = css.indexOf(`\n${selector} {`);
      if (start < 0) throw new Error(`No rule ${selector}`);
      return css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
    };
    const box = rule('.ui-subtabs[role="tablist"]');
    expect(box).toContain("border-radius: 8px;");
    expect(box).toContain("border: 1px solid var(--btn-edge);");
    const one = rule('.ui-subtabs [role="tab"]');
    expect(one).toContain("border-radius: 0;");
    expect(one).toContain("min-height: 44px;");
    const chosen = rule('.ui-subtabs [role="tab"][aria-selected="true"]');
    expect(chosen).toContain("background: var(--selected);");
    expect(chosen).toContain("inset 0 -3px 0 var(--primary)");
    expect(chosen).not.toContain("var(--on-primary)");
    expect(rule(".ui-subtab-count")).not.toContain("border-radius");
    expect(css).not.toMatch(/\.ui-subtab[^{]*\{[^}]*999px/);
    expect(rule('.shell-page > .ui-subtabs[role="tablist"]')).toContain(
      "margin-bottom: 0;",
    );
    expect(rule('.shell-page > .ui-stack[role="tabpanel"]')).toContain(
      "gap: inherit;",
    );
    expect(rule(".ui-stack")).toContain("gap: 16px;");
  });
});
