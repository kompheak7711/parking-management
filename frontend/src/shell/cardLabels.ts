import { type RefObject, useLayoutEffect, useRef } from "react";

/**
 * Staff review fix 4 (owner 16/11/2026): on a phone a table is a list of cards
 * ("ui-rowcards"). Each cell after the first is labelled with its column heading, read from
 * the table's head after every draw; a column whose heading is for screen readers only (the
 * buttons) gets no label.
 */
export function useCardLabels(): RefObject<HTMLTableElement | null> {
  const table = useRef<HTMLTableElement>(null);
  useLayoutEffect(() => {
    const element = table.current;
    if (element === null) return;
    const heads = [...element.querySelectorAll("thead th")].map((th) =>
      th.querySelector(".ui-sr") !== null ? "" : th.textContent.trim(),
    );
    for (const row of element.querySelectorAll("tbody tr")) {
      [...row.children].forEach((cell, index) => {
        if (!(cell instanceof HTMLElement)) return;
        const label = index === 0 ? "" : (heads[index] ?? "");
        if (label === "") delete cell.dataset.label;
        else cell.dataset.label = label;
      });
    }
  });
  return table;
}
