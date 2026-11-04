// V1.1 part 6 (DL-123): Office › Invoices › Quotations (mock-up round 16). "#/quotations" is the
// list with three summary cards that filter it; "#/quotations/qt:<id>" one Quotation;
// "#/quotations/new" New Quotation; "#/quotations/new:<id>" a new Quotation from another one
// (a new version that replaces a waiting one, or Make a new Quotation after it closed). Buttons
// show only to a person who holds the right; the server checks every right again.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import type { LeaseApi } from "../leaseClient";
import {
  type ProductsApi,
  productsApi as defaultProductsApi,
} from "../products/productsClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress, useHashDetail } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import { NewQuotationForm } from "./NewQuotation";
import { QuotationDetail } from "./QuotationDetail";
import {
  type Quotation,
  type QuotationState,
  type QuotationsApi,
  quotationsApi as defaultQuotationsApi,
} from "./quotationsClient";
import { qt, type QuotationsTextKey } from "./text";

export interface QuotationsPageProps {
  language: Language;
  propertyId: string;
  /** Only the page that is shown loads; a hidden page waits until it is opened. */
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  leaseApi: Pick<LeaseApi, "list">;
  api?: QuotationsApi;
  productsApi?: Pick<ProductsApi, "catalogue" | "locations">;
  /** Today in Phnom Penh; tests pass a fixed day. */
  today?: string;
}

const CHIPS: Record<QuotationState, [Tone, ShellIcon | undefined]> = {
  WAITING: ["warn", "clock"],
  SIGNED: ["ok", "check"],
  REPLACED: ["neutral", undefined],
  REFUSED: ["neutral", "x"],
  EXPIRED: ["err", "alert"],
};

export function QuotationChip({
  language,
  state,
}: {
  language: Language;
  state: QuotationState;
}) {
  const [tone, icon] = CHIPS[state];
  return (
    <Chip icon={icon} tone={tone}>
      {qt(language, `st_${state}`)}
    </Chip>
  );
}

type Card = "all" | "wait" | "signed" | "closed";

const CARDS: [Card, ShellIcon, Tone | "brand", QuotationsTextKey][] = [
  ["all", "list", "brand", "c_all"],
  ["wait", "clock", "warn", "c_wait"],
  ["signed", "check", "ok", "c_signed"],
  ["closed", "x", "neutral", "c_closed"],
];

function inCard(quotation: Quotation, card: Card): boolean {
  if (card === "all") return true;
  if (card === "wait") return quotation.state === "WAITING";
  if (card === "signed") return quotation.state === "SIGNED";
  return quotation.state === "EXPIRED" || quotation.state === "REFUSED";
}

/** A plain click opens the record here; with a key held the browser opens the link itself. */
function plainClick(event: React.MouseEvent): boolean {
  return !(
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

export function QuotationsPage({
  language,
  propertyId,
  active,
  capabilities,
  leaseApi,
  api = defaultQuotationsApi,
  productsApi = defaultProductsApi,
  today,
}: QuotationsPageProps) {
  const detail = useHashDetail("quotations");
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const [quotations, setQuotations] = useState<Quotation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [card, setCard] = useState<Card>("all");
  const [flash, setFlash] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    void api
      .list(propertyId)
      .then((found) => {
        if (operation === sequence.current) setQuotations(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId]);

  // Another Property never shows the Quotations of the one before.
  useEffect(() => {
    sequence.current++;
    setQuotations(null);
  }, [propertyId]);

  // Read again each time the page is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active && detail === null) load();
  }, [active, detail, load]);

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{qt(language, "no_property")}</p>
      </div>
    );
  }

  if (detail?.startsWith("qt:") === true) {
    const quotationId = detail.slice(3);
    return (
      <QuotationDetail
        api={api}
        flash={flash}
        key={`${quotationId}:${propertyId}`}
        language={language}
        may={may}
        onFlashShown={() => {
          setFlash(null);
        }}
        productsApi={productsApi}
        propertyId={propertyId}
        quotationId={quotationId}
        today={today}
      />
    );
  }
  if (
    (detail === "new" || detail?.startsWith("new:") === true) &&
    may("quotations.make")
  ) {
    const fromId = detail === "new" ? null : detail.slice(4);
    return (
      <NewQuotationForm
        api={api}
        fromId={fromId}
        key={`${detail}:${propertyId}`}
        language={language}
        leaseApi={leaseApi}
        mayLower={may("quotations.lower_price")}
        onSaved={(made) => {
          setFlash(qt(language, "saved", made.quotation_number));
          openPageInAddress("quotations", true, `qt:${made.quotation_id}`);
        }}
        productsApi={productsApi}
        propertyId={propertyId}
      />
    );
  }

  const failure = failed && (
    <div className="ui-notice warn" role="status">
      <Icon name="alert" />
      <p>{qt(language, "failed")}</p>
      <button className="ui-btn" onClick={load} type="button">
        {qt(language, "retry")}
      </button>
    </div>
  );
  if (quotations === null)
    return (
      failure || (
        <p className="ui-muted" role="status">
          {qt(language, "loading")}
        </p>
      )
    );

  const rows = quotations.filter((quotation) => inCard(quotation, card));
  const open = (id: string) => {
    openPageInAddress("quotations", false, `qt:${id}`);
  };
  return (
    <>
      {failure}
      <div className="ui-head">
        <p>{qt(language, "sub")}</p>
        {may("quotations.make") && (
          <div className="ui-actions">
            <a
              className="ui-btn primary"
              href={hashForPage("quotations", "new")}
            >
              <Icon name="plus" />
              {qt(language, "new_btn")}
            </a>
          </div>
        )}
      </div>
      <div className="ui-kpis">
        {CARDS.map(([value, icon, tone, key]) => {
          const count = quotations.filter((quotation) =>
            inCard(quotation, value),
          ).length;
          return (
            <CountCard
              icon={icon}
              key={value}
              label={qt(language, key)}
              note={qt(language, `${key}_s` as QuotationsTextKey)}
              onPress={() => {
                setCard(card === value && value !== "all" ? "all" : value);
              }}
              pressed={card === value}
              tone={count === 0 && value !== "all" ? "none" : tone}
              value={count}
            />
          );
        })}
      </div>
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {qt(
              language,
              "showing",
              qt(
                language,
                CARDS.find(([value]) => value === card)?.[3] ?? "c_all",
              ),
            )}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {qt(language, "show_all")}
            </button>
          </div>
        )}
        {rows.length === 0 ? (
          <p className="ui-empty">{qt(language, "none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{qt(language, "col_no")}</th>
                    <th scope="col">{qt(language, "col_cust")}</th>
                    <th className="ui-wide" scope="col">
                      {qt(language, "col_made")}
                    </th>
                    <th className="ui-wide" scope="col">
                      {qt(language, "col_until")}
                    </th>
                    <th className="r" scope="col">
                      {qt(language, "col_amount")}
                    </th>
                    <th scope="col">{qt(language, "col_status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((quotation) => (
                    <tr
                      className="ui-row"
                      key={quotation.quotation_id}
                      onClick={() => {
                        open(quotation.quotation_id);
                      }}
                    >
                      <td>
                        <a
                          className="ui-no ui-num"
                          href={hashForPage(
                            "quotations",
                            `qt:${quotation.quotation_id}`,
                          )}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (!plainClick(event)) return;
                            event.preventDefault();
                            open(quotation.quotation_id);
                          }}
                        >
                          {quotation.quotation_number}
                        </a>
                      </td>
                      <td>
                        {quotation.customer_name}
                        {quotation.unit_number !== null && (
                          <span className="ui-sub2">
                            {quotation.unit_number}
                          </span>
                        )}
                      </td>
                      <td className="ui-wide ui-num">
                        {dayText(quotation.made_on)}
                      </td>
                      <td className="ui-wide ui-num">
                        {dayText(quotation.valid_until)}
                      </td>
                      <td className="r ui-num">
                        {usdFromCents(quotation.total_usd_cents)}
                      </td>
                      <td>
                        <QuotationChip
                          language={language}
                          state={quotation.state}
                        />
                        {quotation.invoice_number !== null ? (
                          <span className="ui-sub2 ui-num">
                            {quotation.invoice_number}
                          </span>
                        ) : (
                          quotation.replaced_by_number !== null && (
                            <span className="ui-sub2">
                              {qt(
                                language,
                                "replaced_by",
                                quotation.replaced_by_number,
                              )}
                            </span>
                          )
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {rows.length === 1
                ? qt(language, "n1")
                : qt(language, "n", rows.length)}
            </div>
          </>
        )}
      </div>
    </>
  );
}
