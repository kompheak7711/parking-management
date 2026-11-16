// UI v81 (B4, design v81 top bar): one search box for Customers (name or phone) and Units
// (number). Display only: it reads the same lists the Customers and Units pages read, with the
// same rights, and opens the record. Invoice and Lease numbers are not searched yet: the server
// has no number search for them (open question in docs/ui-audit/01_UI_AUDIT_REPORT.md).

import { useEffect, useId, useRef, useState } from "react";

import type { Language } from "../signInText";
import { Icon } from "./icons";
import { hashForPage } from "./navigation";

const TEXT = {
  label: ["Search", "ស្វែងរក"], // new
  // Owner 07/11/2026: the design's placeholder (i18n.js search_ph).
  placeholder: [
    "Search Invoice, Receipt, Customer or Unit",
    "ស្វែងរក វិក្កយបត្រ បង្កាន់ដៃ អតិថិជន ឬបន្ទប់",
  ],
  // new: the server has no number search yet (open question in the UI audit report).
  numbers: [
    "Invoice and Receipt numbers cannot be searched yet. Open Invoices or Payments and use the filters there.",
    "មិនទាន់អាចស្វែងរកលេខវិក្កយបត្រ និងបង្កាន់ដៃបានទេ។ សូមបើកវិក្កយបត្រ ឬការបង់ប្រាក់ ហើយប្រើតម្រងនៅទីនោះ។",
  ],
  none: ["Nothing found for “{0}”.", "រកមិនឃើញ “{0}” ទេ។"], // new
  customer: ["Customer", "អតិថិជន"], // new
  unit: ["Unit", "បន្ទប់"], // new
  failed: [
    "Search did not answer. Try again.",
    "ការស្វែងរកមិនឆ្លើយ។ សូមព្យាយាមម្តងទៀត។",
  ], // new
} as const;

function tt(language: Language, key: keyof typeof TEXT, value = ""): string {
  return TEXT[key][language === "en" ? 0 : 1].replace("{0}", value);
}

export interface SearchSources {
  /** Customers whose name or phone matches; left out when the person may not read them. */
  customers?: (
    propertyId: string,
    query: string,
  ) => Promise<readonly { customer_id: string; legal_name: string }[]>;
  /** Every Unit of the Property (number and id); left out when the person may not read them. */
  units?: (
    propertyId: string,
  ) => Promise<readonly { unit_id: string; unit_number: string }[]>;
}

/** "INV-2026-0001", "PAY-000123", "inv 12": a document number, which the search cannot find yet. */
export function looksLikeDocumentNumber(query: string): boolean {
  return /^(INV|PAY|RCP|RES|QT|PR)[-\s]?\d+/i.test(query.trim());
}

interface Hit {
  kind: "customer" | "unit";
  id: string;
  name: string;
}

export function TopSearch({
  language,
  propertyId,
  sources,
}: {
  language: Language;
  propertyId: string;
  sources: SearchSources;
}) {
  const [text, setText] = useState("");
  const [hits, setHits] = useState<Hit[] | "failed" | null>(null);
  const [active, setActive] = useState(0);
  const listId = useId();
  const box = useRef<HTMLDivElement>(null);
  const query = text.trim();
  // The sources may be new on every page draw; a search runs again only when the text changes.
  const from = useRef(sources);
  from.current = sources;

  useEffect(() => {
    if (query.length < 2 || propertyId === "") {
      setHits(null);
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => {
      const wanted = query.toLowerCase();
      void Promise.all([
        from.current.customers?.(propertyId, query) ?? Promise.resolve([]),
        from.current.units?.(propertyId) ?? Promise.resolve([]),
      ]).then(
        ([customers, units]) => {
          if (!current) return;
          setActive(0);
          setHits([
            ...units
              .filter((unit) => unit.unit_number.toLowerCase().includes(wanted))
              .slice(0, 5)
              .map((unit) => ({
                kind: "unit" as const,
                id: unit.unit_id,
                name: unit.unit_number,
              })),
            ...customers.slice(0, 5).map((customer) => ({
              kind: "customer" as const,
              id: customer.customer_id,
              name: customer.legal_name,
            })),
          ]);
        },
        () => {
          if (current) setHits("failed");
        },
      );
    }, 250);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [query, propertyId]);

  const open = (hit: Hit) => {
    setText("");
    setHits(null);
    window.location.hash = hashForPage(
      hit.kind === "unit" ? "units" : "customers",
      hit.id,
    ).replace(/^#/, "");
  };
  const list = Array.isArray(hits) ? hits : [];
  const shown = hits !== null;

  return (
    <div
      className="shell-search"
      onBlur={(event) => {
        if (!box.current?.contains(event.relatedTarget as Node | null))
          setHits(null);
      }}
      ref={box}
      role="search"
    >
      <Icon name="search" small />
      <input
        aria-activedescendant={
          list.length > 0 ? `${listId}-${String(active)}` : undefined
        }
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={shown}
        aria-label={tt(language, "label")}
        onChange={(event) => {
          setText(event.currentTarget.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setText("");
            setHits(null);
          } else if (event.key === "ArrowDown" && list.length > 0) {
            event.preventDefault();
            setActive((active + 1) % list.length);
          } else if (event.key === "ArrowUp" && list.length > 0) {
            event.preventDefault();
            setActive((active - 1 + list.length) % list.length);
          } else if (event.key === "Enter") {
            const hit = list[active];
            if (hit !== undefined) open(hit);
          }
        }}
        placeholder={tt(language, "placeholder")}
        role="combobox"
        type="search"
        value={text}
      />
      {shown && (
        <ul className="shell-search-list" id={listId} role="listbox">
          {hits === "failed" ? (
            <li className="shell-search-note">{tt(language, "failed")}</li>
          ) : list.length === 0 ? (
            <li className="shell-search-note">
              {looksLikeDocumentNumber(query)
                ? tt(language, "numbers")
                : tt(language, "none", query)}
            </li>
          ) : (
            list.map((hit, index) => (
              <li
                aria-selected={index === active}
                id={`${listId}-${String(index)}`}
                key={`${hit.kind}:${hit.id}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  open(hit);
                }}
                role="option"
              >
                <Icon
                  name={hit.kind === "unit" ? "units" : "customers"}
                  small
                />
                <span className={hit.kind === "unit" ? "ui-num" : undefined}>
                  {hit.name}
                </span>
                <small className="ui-muted">{tt(language, hit.kind)}</small>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
