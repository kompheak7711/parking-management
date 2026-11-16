// V1.1 part 4 (DL-121): Building › Products, with the tabs Products, Stock movements and
// Locations. Buttons show only to a person who holds the right; the server checks every right
// again, sets every price and keeps stock from going below 0.

import "../shell/screens.css";

import { useCallback, useEffect, useRef, useState } from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { PageHead } from "../shell/pageHead";
import { Chip, RowMenu } from "../shell/ui";
import { useShowFromAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import {
  MarkUpDialog,
  PriceHistoryDialog,
  ProductDialog,
  categoryName,
  productName,
} from "./ProductDialogs";
import {
  type Catalogue,
  dollars,
  type Locations,
  type Movement,
  percent,
  type Place,
  type Product,
  ProductsError,
  type ProductsApi,
  productsApi as defaultProductsApi,
} from "./productsClient";
import {
  AddPlaceDialog,
  type MovementMode,
  MovementDialog,
  placeName,
} from "./StockDialogs";
import { ServiceCostDialog } from "./ProductDialogs";
import { pt, unitName } from "./text";

export type ProductsTab = "products" | "stock" | "locations";

export interface ProductsPageProps {
  language: Language;
  propertyId: string;
  /** Only the tab that is shown loads; a hidden tab waits until it is opened. */
  active: boolean;
  tab: ProductsTab;
  capabilities: ReadonlySet<string> | null;
  api?: ProductsApi;
}

type Open =
  | { kind: "add" }
  | { kind: "edit"; product: Product }
  | { kind: "mark-ups"; product: Product }
  | { kind: "cost"; product: Product }
  | { kind: "prices"; product: Product }
  | { kind: "move"; mode: MovementMode }
  | { kind: "place"; unitId: string; unitNumber: string };

interface Data {
  catalogue: Catalogue | null;
  locations: Locations | null;
  movements: Movement[] | null;
}

function refusal(language: Language, error: unknown): string {
  if (error instanceof ProductsError) {
    if (error.status === 403) return pt(language, "f_right");
    if (error.status === 412) return pt(language, "f_stale");
    if ((error.status === 409 || error.status === 422) && error.detail !== null)
      return pt(language, "f_refused", error.detail);
  }
  return pt(language, "f_failed");
}

export function ProductsPage({
  language,
  propertyId,
  active,
  tab,
  capabilities,
  api = defaultProductsApi,
}: ProductsPageProps) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setFailed(false);
    const wantsCatalogue = tab !== "locations";
    const wantsLocations = tab !== "products";
    void Promise.all([
      wantsCatalogue ? api.catalogue(propertyId) : Promise.resolve(null),
      wantsLocations ? api.locations(propertyId) : Promise.resolve(null),
      tab === "stock" ? api.movements(propertyId) : Promise.resolve(null),
    ])
      .then(([catalogue, locations, movements]) => {
        if (operation === sequence.current)
          setData({ catalogue, locations, movements });
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, propertyId, tab]);

  // Read again each time the tab is opened, so it shows what others changed meanwhile.
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  function close() {
    setOpen(null);
    setFailure(null);
  }

  function run(
    action: () => Promise<unknown>,
    done: (result: unknown) => string,
  ) {
    setBusy(true);
    setFailure(null);
    action().then(
      (result) => {
        setBusy(false);
        setOpen(null);
        setNotice(done(result));
        load();
      },
      (error: unknown) => {
        setBusy(false);
        setFailure(refusal(language, error));
        if (error instanceof ProductsError && error.status === 412) load();
      },
    );
  }

  if (propertyId === "") {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{pt(language, "no_property")}</p>
      </div>
    );
  }
  if (failed && data === null) {
    return (
      <div className="ui-notice warn" role="status">
        <Icon name="alert" />
        <p>{pt(language, "failed")}</p>
        <button className="ui-btn" onClick={load} type="button">
          {pt(language, "retry")}
        </button>
      </div>
    );
  }
  if (data === null) {
    return (
      <p className="ui-muted" role="status">
        {pt(language, "loading")}
      </p>
    );
  }

  const { catalogue, locations, movements } = data;
  return (
    <>
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      {tab === "products" && catalogue !== null && (
        <ProductsTable
          active={active}
          catalogue={catalogue}
          language={language}
          may={may}
          onOpen={(next) => {
            setNotice(null);
            setOpen(next);
          }}
        />
      )}
      {tab === "stock" && movements !== null && (
        <MovementsTable
          active={active}
          canAdjust={may("stock.adjust")}
          canMove={may("stock.transfer")}
          canPurchase={may("stock.purchase")}
          language={language}
          movements={movements}
          onOpen={(mode) => {
            setNotice(null);
            setOpen({ kind: "move", mode });
          }}
        />
      )}
      {tab === "locations" && locations !== null && (
        <LocationsCards
          canAdd={may("products.manage") && locations.features.length > 0}
          language={language}
          locations={locations}
          onAdd={(unitId, unitNumber) => {
            setNotice(null);
            setOpen({ kind: "place", unitId, unitNumber });
          }}
        />
      )}
      {open !== null &&
        catalogue !== null &&
        (open.kind === "add" || open.kind === "edit") && (
          <ProductDialog
            busy={busy}
            catalogue={catalogue}
            failure={failure}
            language={language}
            onAdd={(product) => {
              run(
                () => api.addProduct(propertyId, product),
                () => pt(language, "pr_added", product.name_en),
              );
            }}
            onChange={(product, change) => {
              run(
                () => api.changeProduct(propertyId, product, change),
                () => pt(language, "pr_saved", change.name_en),
              );
            }}
            onClose={close}
            product={open.kind === "edit" ? open.product : null}
          />
        )}
      {open?.kind === "mark-ups" && catalogue !== null && (
        <MarkUpDialog
          busy={busy}
          catalogue={catalogue}
          failure={failure}
          language={language}
          onClose={close}
          onSave={(change) => {
            run(
              () => api.setMarkUps(propertyId, open.product, change),
              () =>
                pt(language, "pr_saved", productName(open.product, language)),
            );
          }}
          product={open.product}
        />
      )}
      {open?.kind === "cost" && (
        <ServiceCostDialog
          busy={busy}
          failure={failure}
          language={language}
          onClose={close}
          onSave={(cents) => {
            run(
              () => api.setServiceCost(propertyId, open.product, cents),
              () =>
                pt(language, "pr_saved", productName(open.product, language)),
            );
          }}
          product={open.product}
        />
      )}
      {open?.kind === "prices" && (
        <PriceHistoryDialog
          api={api}
          language={language}
          onClose={close}
          product={open.product}
          propertyId={propertyId}
        />
      )}
      {open?.kind === "move" && catalogue !== null && locations !== null && (
        <MovementDialog
          busy={busy}
          catalogue={catalogue}
          failure={failure}
          language={language}
          locations={locations}
          mode={open.mode}
          onClose={close}
          onSave={(movement) => {
            run(
              () => api.recordMovement(propertyId, movement),
              (number) => pt(language, "sm_saved", String(number)),
            );
          }}
        />
      )}
      {open?.kind === "place" && locations !== null && (
        <AddPlaceDialog
          busy={busy}
          failure={failure}
          kinds={locations.features}
          language={language}
          onClose={close}
          onSave={(itemId) => {
            const kind = locations.features.find(
              (item) => item.item_id === itemId,
            );
            run(
              () => api.addPlace(propertyId, open.unitId, itemId),
              (number) =>
                pt(
                  language,
                  "ap_saved",
                  `${open.unitNumber} · ${kind === undefined ? "" : placeName(kind, language)} ${String(number)}`,
                ),
            );
          }}
          places={locations.places.filter(
            (place) => place.unit_id === open.unitId,
          )}
          unitNumber={open.unitNumber}
        />
      )}
    </>
  );
}

function ProductsTable({
  active,
  language,
  catalogue,
  may,
  onOpen,
}: {
  active: boolean;
  language: Language;
  catalogue: Catalogue;
  may: (capability: string) => boolean;
  onOpen: (open: Open) => void;
}) {
  const rules = catalogue.rules;
  // UI v81 round 11: Home's "Low stock" card opens "#/products?show=low": only the products
  // the server marks as low on stock and still sold (what the card counts).
  const [lowOnly, setLowOnlyState] = useState(false);
  const keepShow = useShowFromAddress("products", (show) => {
    if (show === "low" || show === "all") setLowOnlyState(show === "low");
  });
  const setLowOnly = (next: boolean) => {
    setLowOnlyState(next);
    keepShow(next ? "low" : null);
  };
  const isLow = (product: (typeof catalogue.products)[number]) =>
    product.low_stock && !product.discontinued;
  const listed = catalogue.products.filter(
    (product) => !lowOnly || isLow(product),
  );
  return (
    <section aria-labelledby="products-title" className="ui-card pad0">
      {/* Property fix 2 (owner 14/11/2026): the tab row is the page's head, so the card has no
          title of its own and Add product sits at the right end of the tab row. */}
      <h2 className="ui-sr" id="products-title">
        {pt(language, "pr_title")}
      </h2>
      {may("products.manage") && (
        <PageHead
          active={active}
          actions={
            <button
              className="ui-btn primary"
              onClick={() => {
                onOpen({ kind: "add" });
              }}
              type="button"
            >
              <Icon name="plus" small />
              {pt(language, "pr_add")}
            </button>
          }
        />
      )}
      <p className="ui-muted pad">
        {pt(
          language,
          "pr_rules",
          percent(rules.mark_up_basis_points),
          percent(rules.min_mark_up_basis_points),
          rules.max_mark_up_basis_points === null
            ? pt(language, "pr_no_max")
            : percent(rules.max_mark_up_basis_points),
          dollars(rules.price_round_up_usd_cents),
        )}
      </p>
      {catalogue.products.length > 0 && (
        <div className="ui-filters pad">
          <div
            aria-label={pt(language, "pr_stock")}
            className="ui-seg"
            role="group"
          >
            {([false, true] as const).map((value) => (
              <button
                aria-pressed={lowOnly === value}
                key={String(value)}
                onClick={() => {
                  setLowOnly(value);
                }}
                type="button"
              >
                {pt(language, value ? "pr_low" : "pr_all")}{" "}
                <span className="ui-num">
                  {value
                    ? catalogue.products.filter(isLow).length
                    : catalogue.products.length}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      {listed.length === 0 ? (
        <p className="ui-muted pad">
          {pt(
            language,
            catalogue.products.length === 0 ? "pr_none" : "pr_low_none",
          )}
        </p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table ui-pcards ui-prodlist">
            <thead>
              <tr>
                <th scope="col">{pt(language, "pr_sku")}</th>
                <th scope="col">{pt(language, "pr_name")}</th>
                <th scope="col">{pt(language, "pr_category")}</th>
                <th scope="col">{pt(language, "pr_unit")}</th>
                <th scope="col">{pt(language, "pr_stock")}</th>
                <th scope="col">{pt(language, "pr_cost")}</th>
                <th scope="col">{pt(language, "pr_mark_up")}</th>
                <th scope="col">{pt(language, "pr_price")}</th>
                <th scope="col">
                  <span className="ui-sr">{pt(language, "pr_actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {listed.map((product) => {
                const name = productName(product, language);
                return (
                  <tr key={product.product_id}>
                    <td className="ui-num pc-small">{product.sku}</td>
                    <td className="pc-name">
                      <b>{name}</b>
                      {product.discontinued && (
                        <>
                          {" "}
                          <Chip tone="neutral">
                            {pt(language, "pr_discontinued")}
                          </Chip>
                        </>
                      )}
                      {product.low_stock && !product.discontinued && (
                        <>
                          {" "}
                          <Chip tone="warn">{pt(language, "pr_low")}</Chip>
                        </>
                      )}
                    </td>
                    <td className="pc-hide">
                      {categoryName(catalogue, product.category_code, language)}
                    </td>
                    <td className="pc-hide">
                      {unitName(product.measure_unit, language)}
                    </td>
                    <td className="ui-num pc-small">
                      {product.kind === "SERVICE" ? (
                        pt(language, "pr_service")
                      ) : (
                        <>
                          <span className="pc-label">
                            {pt(language, "pr_stock")}{" "}
                          </span>
                          {product.stock}
                          <span className="pc-label">
                            {" "}
                            {unitName(product.measure_unit, language)}
                          </span>
                        </>
                      )}
                    </td>
                    <td className="ui-num pc-hide">
                      {dollars(product.cost_usd_cents)}
                    </td>
                    <td className="ui-num pc-hide">
                      {percent(product.mark_up_basis_points)}
                    </td>
                    <td className="ui-num pc-end">
                      {product.price_usd_cents === null ? (
                        <span className="ui-muted">
                          {pt(language, "pr_no_price")}
                        </span>
                      ) : (
                        <b>{dollars(product.price_usd_cents)}</b>
                      )}
                    </td>
                    <td>
                      {/* Property fix 1 (owner 14/11/2026): the row's buttons in one small
                          menu, so every row stays one line high. */}
                      <RowMenu
                        label={pt(language, "pr_edit")}
                        name={`${pt(language, "pr_edit")}: ${name}`}
                      >
                        {may("products.manage") && (
                          <button
                            aria-label={`${pt(language, "pr_details")}: ${name}`}
                            className="ui-btn"
                            onClick={() => {
                              onOpen({ kind: "edit", product });
                            }}
                            type="button"
                          >
                            {pt(language, "pr_details")}
                          </button>
                        )}
                        {may("products.prices") && (
                          <button
                            aria-label={`${pt(language, "pr_set_mark_up")}: ${name}`}
                            className="ui-btn"
                            onClick={() => {
                              onOpen({ kind: "mark-ups", product });
                            }}
                            type="button"
                          >
                            {pt(language, "pr_set_mark_up")}
                          </button>
                        )}
                        {product.kind === "SERVICE" &&
                          may("products.manage") && (
                            <button
                              aria-label={`${pt(language, "pr_set_cost")}: ${name}`}
                              className="ui-btn"
                              onClick={() => {
                                onOpen({ kind: "cost", product });
                              }}
                              type="button"
                            >
                              {pt(language, "pr_set_cost")}
                            </button>
                          )}
                        <button
                          aria-label={`${pt(language, "pr_prices")}: ${name}`}
                          className="ui-btn"
                          onClick={() => {
                            onOpen({ kind: "prices", product });
                          }}
                          type="button"
                        >
                          {pt(language, "pr_prices")}
                        </button>
                      </RowMenu>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="ui-tfoot">
        <span>{pt(language, "pr_note")}</span>
      </div>
    </section>
  );
}

/** Property fix 9 (owner 14/11/2026): a move is one row, "from → to", not an out row and an
 *  in row with the same number. Rows without a partner stay as they are. */
function moveRows(
  movements: Movement[],
): { movement: Movement; to: Movement | null }[] {
  const rows: { movement: Movement; to: Movement | null }[] = [];
  for (const movement of movements) {
    if (movement.kind === "TRANSFER_IN") {
      const pair = movements.some(
        (other) =>
          other.kind === "TRANSFER_OUT" &&
          other.movement_number === movement.movement_number,
      );
      if (pair) continue;
    }
    const to =
      movement.kind === "TRANSFER_OUT"
        ? (movements.find(
            (other) =>
              other.kind === "TRANSFER_IN" &&
              other.movement_number === movement.movement_number,
          ) ?? null)
        : null;
    rows.push({ movement, to });
  }
  return rows;
}

function placeText(movement: Movement, language: Language): string {
  return `${movement.unit_number} · ${placeName(
    { name_en: movement.place_name_en, name_kh: movement.place_name_kh },
    language,
  )} ${String(movement.place_number)}`;
}

function MovementsTable({
  active,
  language,
  movements,
  canPurchase,
  canMove,
  canAdjust,
  onOpen,
}: {
  active: boolean;
  language: Language;
  movements: Movement[];
  canPurchase: boolean;
  canMove: boolean;
  canAdjust: boolean;
  onOpen: (mode: MovementMode) => void;
}) {
  const buttons: [
    MovementMode,
    boolean,
    "sm_purchase" | "sm_transfer" | "sm_adjust",
  ][] = [
    ["PURCHASE", canPurchase, "sm_purchase"],
    ["TRANSFER", canMove, "sm_transfer"],
    ["ADJUST", canAdjust, "sm_adjust"],
  ];
  return (
    <section aria-labelledby="stock-title" className="ui-card pad0">
      {/* Property fix 2 (owner 14/11/2026): the buttons sit at the right end of the tab row. */}
      <h2 className="ui-sr" id="stock-title">
        {pt(language, "sm_title")}
      </h2>
      <PageHead
        active={active}
        actions={buttons
          .filter(([, allowed]) => allowed)
          .map(([mode, , key]) => (
            <button
              className={mode === "PURCHASE" ? "ui-btn primary" : "ui-btn"}
              key={mode}
              onClick={() => {
                onOpen(mode);
              }}
              type="button"
            >
              {mode === "PURCHASE" && <Icon name="plus" small />}
              {mode === "TRANSFER" && <Icon name="swap" small />}
              {pt(language, key)}
            </button>
          ))}
      />
      {movements.length === 0 ? (
        <p className="ui-muted pad">{pt(language, "sm_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table ui-pcards ui-movelist">
            <thead>
              <tr>
                <th scope="col">{pt(language, "sm_number")}</th>
                <th scope="col">{pt(language, "sm_date")}</th>
                <th scope="col">{pt(language, "sm_kind")}</th>
                <th scope="col">{pt(language, "sm_product")}</th>
                <th scope="col">{pt(language, "sm_qty")}</th>
                <th scope="col">{pt(language, "sm_place")}</th>
              </tr>
            </thead>
            <tbody>
              {moveRows(movements).map(({ movement, to }) => {
                const out =
                  to === null &&
                  (movement.kind === "ADJUSTMENT_OUT" ||
                    movement.kind === "TRANSFER_OUT" ||
                    movement.kind === "SALE");
                const detail = [
                  movement.unit_cost_usd_cents === null
                    ? null
                    : dollars(movement.unit_cost_usd_cents),
                  movement.supplier,
                  movement.receipt_reference,
                  movement.reason,
                  movement.recorded_by_name,
                ]
                  .filter(
                    (part): part is string => part !== null && part !== "",
                  )
                  .join(" · ");
                return (
                  <tr key={`${movement.movement_number}-${movement.kind}`}>
                    <td className="ui-num pc-small">
                      {movement.movement_number}
                    </td>
                    <td className="pc-small">
                      {dayText(movement.business_date)}
                    </td>
                    <td className="pc-end">
                      <Chip tone={to !== null ? "info" : out ? "warn" : "ok"}>
                        {pt(
                          language,
                          to !== null ? "sm_moved" : `sm_${movement.kind}`,
                        )}
                      </Chip>
                    </td>
                    <td className="pc-name ui-wrapcell">
                      {movement.sku} · {movement.product_name_en}
                      {/* Property fix 9: the details and who recorded it, small under the
                          product, so the table fits the screen. */}
                      {detail !== "" && (
                        <span className="ui-subline">{detail}</span>
                      )}
                    </td>
                    <td className="ui-num pc-end">
                      {to !== null ? "" : out ? "−" : "+"}
                      {movement.quantity}{" "}
                      {unitName(movement.measure_unit, language)}
                    </td>
                    <td className="pc-full">
                      {placeText(movement, language)}
                      {to !== null && <> → {placeText(to, language)}</>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="ui-tfoot">
        <span>{pt(language, "sm_note")}</span>
      </div>
    </section>
  );
}

function LocationsCards({
  language,
  locations,
  canAdd,
  onAdd,
}: {
  language: Language;
  locations: Locations;
  canAdd: boolean;
  onAdd: (unitId: string, unitNumber: string) => void;
}) {
  // Units not for rent (the warehouse) always show; a Unit for rent only when it holds items.
  const units = new Map<string, Place[]>();
  for (const place of locations.places) {
    units.set(place.unit_id, [...(units.get(place.unit_id) ?? []), place]);
  }
  const shown = [...units.values()].filter(
    (places) =>
      places[0]?.for_rent === false ||
      places.some((place) => place.stock.length > 0),
  );
  return (
    <>
      {shown.length === 0 && (
        <p className="ui-muted">{pt(language, "lo_none")}</p>
      )}
      {shown.map((places) => {
        const first = places[0];
        if (first === undefined) return null;
        const headingId = `lo-${first.unit_id}`;
        return (
          <section
            aria-labelledby={headingId}
            className="ui-card pad0"
            key={first.unit_id}
          >
            <header className="ui-chead pad">
              <h2 id={headingId}>
                {/* Owner 14/11/2026: the Unit number only ("W01"), no "Not for rent" chip. */}
                {first.unit_number}
              </h2>
              {canAdd && (
                <span className="ui-actions">
                  <button
                    aria-label={`${pt(language, "lo_add_place")}: ${first.unit_number}`}
                    className="ui-btn"
                    onClick={() => {
                      onAdd(first.unit_id, first.unit_number);
                    }}
                    type="button"
                  >
                    <Icon name="plus" small />
                    {pt(language, "lo_add_place")}
                  </button>
                </span>
              )}
            </header>
            <div className="ui-tablewrap">
              <table className="ui-table ui-loclist">
                <thead>
                  <tr>
                    <th scope="col">{pt(language, "lo_place")}</th>
                    <th scope="col">{pt(language, "lo_holds")}</th>
                  </tr>
                </thead>
                <tbody>
                  {places.map((place) => (
                    <tr key={`${place.item_id}-${String(place.number)}`}>
                      <td>
                        {placeName(place, language)} {place.number}
                      </td>
                      <td>
                        {place.stock.length === 0 ? (
                          <span className="ui-muted">
                            {pt(language, "lo_empty")}
                          </span>
                        ) : (
                          // Property fix 10 (owner 14/11/2026): one item per line.
                          <ul className="ui-holds">
                            {place.stock.map((line) => (
                              <li key={line.product_id}>
                                {line.sku} {line.name_en}{" "}
                                <span className="ui-nowrap">
                                  × {line.quantity}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
      <p className="ui-muted">{pt(language, "lo_note")}</p>
    </>
  );
}
