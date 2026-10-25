// V1-058 R2: the Customers list (DESIGN.md "Customers (round 2)"): a search box, four count
// cards that filter the table, and the table of Customers. Typing filters by name, phone and
// Unit at once; pressing Search also asks the server, which finds a whole ID or passport
// number without ever sending the number back (SEC-041, DL-078 answer 4).

import { FormEvent, useState } from "react";

import type { CustomerListItem } from "../customerClient";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { ct } from "./text";
import {
  CustomerKind,
  CustomerStanding,
  CustomersData,
  phoneKey,
} from "./customersData";

const KIND_CHIPS: Record<CustomerKind, [Tone, ShellIcon | undefined]> = {
  tenant: ["ok", "check"],
  other: ["info", undefined],
  res: ["info", "calendar"],
  former: ["neutral", undefined],
  none: ["neutral", undefined],
};

export function KindChip({
  language,
  kind,
}: {
  language: Language;
  kind: CustomerKind;
}) {
  const [tone, icon] = KIND_CHIPS[kind];
  return (
    <Chip icon={icon} tone={tone}>
      {ct(language, `k_${kind}`)}
    </Chip>
  );
}

const CARDS: [Exclude<CustomerKind, "none">, ShellIcon, Tone | "brand"][] = [
  ["tenant", "check", "ok"],
  ["other", "customers", "brand"],
  ["res", "calendar", "info"],
  ["former", "clock", "neutral"],
];

export interface ServerMatch {
  text: string;
  ids: ReadonlySet<string>;
}

export function CustomersList({
  language,
  data,
  standings,
  serverMatch,
  searching,
  onSearch,
  onAdd,
}: {
  language: Language;
  data: CustomersData;
  standings: ReadonlyMap<string, CustomerStanding>;
  /** The Customers the server found for the text last searched, or null. */
  serverMatch: ServerMatch | null;
  searching: boolean;
  onSearch: (text: string) => void;
  /** Null when the person may not add Customers. */
  onAdd: (() => void) | null;
}) {
  const [text, setText] = useState("");
  const [card, setCard] = useState<Exclude<CustomerKind, "none"> | "all">(
    "all",
  );

  const needle = text.trim().toLowerCase();
  // Only a text of digits, spaces and + ( ) - is a phone number; "N0123456" is not.
  const digits = /^[\d\s+()-]+$/.test(needle) ? phoneKey(needle) : "";
  const standing = (customer: CustomerListItem) =>
    standings.get(customer.customer_id) ?? {
      kind: "none" as const,
      role: null,
      unitNumber: null,
      unitId: null,
    };
  const base = data.customers.filter((customer) => {
    if (needle === "") return true;
    if (
      serverMatch?.text === text.trim() &&
      serverMatch.ids.has(customer.customer_id)
    )
      return true;
    const unit = standing(customer).unitNumber?.toLowerCase() ?? "";
    return (
      customer.legal_name.toLowerCase().includes(needle) ||
      (digits.length >= 3 &&
        phoneKey(customer.phone_number ?? "").includes(digits)) ||
      (unit !== "" && unit === needle)
    );
  });
  const shown = base.filter(
    (customer) => card === "all" || standing(customer).kind === card,
  );
  const unknown = data.leases === null || data.reservations === null;
  const dash = <span className="ui-muted">—</span>;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (text.trim() !== "") onSearch(text.trim());
  }

  return (
    <>
      <div className="ui-head">
        <p>{ct(language, "sub", data.customers.length)}</p>
        {onAdd !== null && (
          <div className="ui-actions">
            <button className="ui-btn primary" onClick={onAdd} type="button">
              <Icon name="plus" />
              {ct(language, "add")}
            </button>
          </div>
        )}
      </div>
      <form className="ui-filters" onSubmit={submit} role="search">
        <label className="ui-sr" htmlFor="customers-search">
          {ct(language, "search")}
        </label>
        <input
          className="ui-search"
          id="customers-search"
          maxLength={255}
          onChange={(event) => {
            setText(event.currentTarget.value);
          }}
          placeholder={ct(language, "search")}
          type="search"
          value={text}
        />
        <button className="ui-btn" disabled={searching} type="submit">
          <Icon name="search" />
          {ct(language, "search_button")}
        </button>
        {text !== "" && (
          <button
            className="ui-btn link"
            onClick={() => {
              setText("");
            }}
            type="button"
          >
            {ct(language, "clear_search")}
          </button>
        )}
      </form>
      {/* Without Leases or Reservations the counts would be wrong, so they are not shown. */}
      {!unknown && (
        <div className="ui-kpis">
          {CARDS.map(([value, icon, tone]) => (
            <CountCard
              icon={icon}
              key={value}
              label={ct(language, `c_${value}`)}
              note={ct(language, `c_${value}_s`)}
              onPress={() => {
                setCard(card === value ? "all" : value);
              }}
              pressed={card === value}
              tone={tone}
              value={
                base.filter((customer) => standing(customer).kind === value)
                  .length
              }
            />
          ))}
        </div>
      )}
      {unknown && (
        <div className="ui-notice">
          <Icon name="info" />
          <p>{ct(language, "tenants_hidden")}</p>
        </div>
      )}
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {ct(language, "showing", ct(language, `c_${card}`))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {ct(language, "show_all")}
            </button>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">{ct(language, "none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{ct(language, "name")}</th>
                    <th scope="col">{ct(language, "phone")}</th>
                    <th scope="col">{ct(language, "unit")}</th>
                    <th scope="col">{ct(language, "relationship")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((customer) => {
                    const own = standing(customer);
                    return (
                      <tr
                        className="ui-row"
                        key={customer.customer_id}
                        onClick={() => {
                          openPageInAddress(
                            "customers",
                            false,
                            customer.customer_id,
                          );
                        }}
                      >
                        <td>
                          <a
                            className="ui-no"
                            href={hashForPage(
                              "customers",
                              customer.customer_id,
                            )}
                            onClick={(event) => {
                              event.stopPropagation();
                              // A plain click opens the Customer here; with a key held the
                              // browser opens the link as it normally does.
                              if (
                                event.button !== 0 ||
                                event.metaKey ||
                                event.ctrlKey ||
                                event.shiftKey ||
                                event.altKey
                              )
                                return;
                              event.preventDefault();
                              openPageInAddress(
                                "customers",
                                false,
                                customer.customer_id,
                              );
                            }}
                          >
                            {customer.legal_name}
                          </a>
                          {!customer.active && (
                            <span className="ui-sub2">
                              {ct(language, "deactivated")}
                            </span>
                          )}
                        </td>
                        <td className="ui-num">
                          {customer.phone_number ?? dash}
                        </td>
                        <td className="ui-num">
                          {unknown ? dash : (own.unitNumber ?? dash)}
                        </td>
                        <td>
                          {unknown ? (
                            dash
                          ) : (
                            <KindChip kind={own.kind} language={language} />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {shown.length === 1
                ? ct(language, "n1")
                : ct(language, "n", shown.length)}
            </div>
          </>
        )}
      </div>
      <p className="ui-muted ui-small">{ct(language, "money_later")}</p>
    </>
  );
}
