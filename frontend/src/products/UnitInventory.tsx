// V1.1 part 5 (DL-122): the Unit inventory on the Unit page. What is in a Unit is worked out from
// the stock movements (DESIGN.md round 18): the card shows "7 items in 3 places" and opens the
// Unit inventory form (Location | Item | Storage | Qty, with New purchase at the top right and
// "Now in this Unit" with Take out). An item enters a Unit only by a Transfer from storage, or by
// a Purchase into storage that then fills a row. Take out sends it back to storage (Transfer) or
// records it as Broken or lost (Adjustment out, Manager or Owner).

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { productName } from "./ProductDialogs";
import {
  type Catalogue,
  centsFromText,
  dollars,
  type Locations,
  type NewMovement,
  type Place,
  type PlaceRef,
  percent,
  priceFor,
  type Product,
  ProductsError,
  type ProductsApi,
  quantityFromText,
  WHOLE_UNITS,
} from "./productsClient";
import { placeLabel, placeName } from "./StockDialogs";
import { type ProductsTextKey, pt, unitName } from "./text";

/** Only these categories go into a Unit (round 18). */
const UNIT_CATEGORIES: ReadonlySet<string> = new Set([
  "FURNITURE",
  "APPLIANCES",
]);

interface Row {
  key: number;
  location: string;
  productId: string;
  storage: string;
  quantity: string;
}

type Mode =
  | { kind: "closed" }
  | { kind: "form" }
  | { kind: "take"; place: Place; productId: string }
  | { kind: "buy" };

function keyOf(place: PlaceRef): string {
  return `${place.unit_id}|${place.item_id}|${String(place.number)}`;
}

function refOf(place: Place): PlaceRef {
  return {
    unit_id: place.unit_id,
    item_id: place.item_id,
    number: place.number,
  };
}

function held(place: Place, productId: string): number {
  return Number(
    place.stock.find((line) => line.product_id === productId)?.quantity ?? "0",
  );
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

function Failure({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

let rowKeys = 0;
function emptyRow(extra: Partial<Row> = {}): Row {
  rowKeys += 1;
  return {
    key: rowKeys,
    location: "",
    productId: "",
    storage: "",
    quantity: "",
    ...extra,
  };
}

function used(row: Row): boolean {
  return (
    row.location !== "" ||
    row.productId !== "" ||
    row.storage !== "" ||
    row.quantity.trim() !== ""
  );
}

/** Keep one empty row at the end, so a new row appears when the last one is used. */
function withSpare(rows: Row[]): Row[] {
  const last = rows[rows.length - 1];
  return last === undefined || used(last) ? [...rows, emptyRow()] : rows;
}

export function UnitInventoryCard({
  language,
  api,
  propertyId,
  unitId,
  unitNumber,
  capabilities,
}: {
  language: Language;
  api: ProductsApi;
  propertyId: string;
  unitId: string;
  unitNumber: string;
  capabilities: ReadonlySet<string> | null;
}) {
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);
  const allowed = may("products.read");
  const [locations, setLocations] = useState<Locations | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<Mode>({ kind: "closed" });
  const [rows, setRows] = useState<Row[]>(() => [emptyRow()]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sequence = useRef(0);

  const load = useCallback(
    (withCatalogue: boolean) => {
      if (!allowed || propertyId === "") return Promise.resolve();
      const operation = ++sequence.current;
      setFailed(false);
      return Promise.all([
        api.locations(propertyId),
        withCatalogue ? api.catalogue(propertyId) : Promise.resolve(null),
      ]).then(
        ([places, products]) => {
          if (operation !== sequence.current) return;
          setLocations(places);
          if (products !== null) setCatalogue(products);
        },
        () => {
          if (operation === sequence.current) setFailed(true);
        },
      );
    },
    [allowed, api, propertyId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  if (!allowed) return null;

  const mine = (locations?.places ?? []).filter(
    (place) => place.unit_id === unitId,
  );
  const holding = mine.filter((place) => place.stock.length > 0);
  const items = holding.reduce(
    (total, place) =>
      total + place.stock.reduce((sum, line) => sum + Number(line.quantity), 0),
    0,
  );
  const storage = (locations?.places ?? []).filter(
    (place) => !place.for_rent && place.unit_id !== unitId,
  );

  function open() {
    setNotice(null);
    setFailure(null);
    void load(true).then(() => {
      setMode({ kind: "form" });
    });
  }

  function back(message: string | null) {
    setFailure(null);
    if (message !== null) setNotice(message);
    void load(true).then(() => {
      setMode({ kind: "form" });
    });
  }

  function close() {
    setMode({ kind: "closed" });
    setFailure(null);
    setRows([emptyRow()]);
  }

  function saveRows(movements: NewMovement[], names: string) {
    setBusy(true);
    setFailure(null);
    api.recordMovements(propertyId, movements).then(
      () => {
        setBusy(false);
        setRows([emptyRow()]);
        setMode({ kind: "closed" });
        setNotice(pt(language, "ui_saved", names, unitNumber));
        void load(false);
      },
      (error: unknown) => {
        setBusy(false);
        setFailure(refusal(language, error));
        void load(true);
      },
    );
  }

  return (
    <div className="ui-sub" aria-labelledby={`ui-${unitId}`} role="group">
      <h3 id={`ui-${unitId}`}>{pt(language, "ui_title")}</h3>
      {notice !== null && (
        <p className="ui-small" role="status">
          <Icon name="check" small /> {notice}
        </p>
      )}
      {failed && locations === null ? (
        <p className="ui-small ui-muted">{pt(language, "failed")}</p>
      ) : locations === null ? (
        <p className="ui-small ui-muted" role="status">
          {pt(language, "loading")}
        </p>
      ) : (
        <p className="ui-small">
          {mine.length === 0
            ? pt(language, "ui_no_places")
            : holding.length === 0
              ? pt(language, "ui_empty")
              : items === 1
                ? pt(language, "ui_count_one")
                : holding.length === 1
                  ? pt(language, "ui_count1", items)
                  : pt(language, "ui_count", items, holding.length)}{" "}
          {mine.length > 0 && (
            <button className="ui-btn" onClick={open} type="button">
              {pt(language, "ui_open")}
            </button>
          )}
        </p>
      )}
      {mode.kind === "form" && locations !== null && catalogue !== null && (
        <InventoryForm
          busy={busy}
          canBuy={may("stock.purchase")}
          canMove={may("stock.transfer")}
          canTakeOut={may("stock.transfer") || may("stock.adjust")}
          catalogue={catalogue}
          failure={failure}
          language={language}
          mine={mine}
          onBuy={() => {
            setFailure(null);
            setMode({ kind: "buy" });
          }}
          onClose={close}
          onRows={setRows}
          onSave={saveRows}
          onTakeOut={(place, productId) => {
            setFailure(null);
            setMode({ kind: "take", place, productId });
          }}
          rows={rows}
          storage={storage}
          unitNumber={unitNumber}
        />
      )}
      {mode.kind === "take" && catalogue !== null && (
        <TakeOutDialog
          busy={busy}
          canAdjust={may("stock.adjust")}
          canMove={may("stock.transfer")}
          failure={failure}
          language={language}
          onBack={() => {
            back(null);
          }}
          onSave={(movement, name) => {
            setBusy(true);
            setFailure(null);
            api.recordMovement(propertyId, movement).then(
              () => {
                setBusy(false);
                back(pt(language, "to_saved", name));
              },
              (error: unknown) => {
                setBusy(false);
                setFailure(refusal(language, error));
              },
            );
          }}
          place={mode.place}
          product={
            catalogue.products.find(
              (item) => item.product_id === mode.productId,
            ) ?? null
          }
          storage={storage}
        />
      )}
      {mode.kind === "buy" && catalogue !== null && (
        <PurchaseDialog
          busy={busy}
          canAdd={may("products.manage")}
          catalogue={catalogue}
          failure={failure}
          language={language}
          onBack={() => {
            back(null);
          }}
          onSave={(change) => {
            setBusy(true);
            setFailure(null);
            const product =
              change.product !== null
                ? Promise.resolve(change.product.product_id)
                : api
                    .addProduct(propertyId, {
                      name_en: change.nameEn,
                      name_kh: change.nameKh,
                      description: null,
                      category_code: change.category,
                      measure_unit: "PIECE",
                      reorder_level: null,
                      reorder_quantity: null,
                      service_cost_usd_cents: null,
                    })
                    .then((after) => {
                      const made = after.products.find(
                        (item) =>
                          item.name_en.toLowerCase() ===
                          change.nameEn.toLowerCase(),
                      );
                      if (made === undefined) throw new ProductsError();
                      return made.product_id;
                    });
            product
              .then((productId) =>
                api
                  .recordMovement(propertyId, {
                    kind: "PURCHASE",
                    product_id: productId,
                    quantity: change.quantity,
                    from: null,
                    to: refOf(change.putIn),
                    unit_cost_usd_cents: change.cost,
                    supplier: change.supplier,
                    receipt_reference: change.receipt,
                    reason: null,
                  })
                  .then(() => productId),
              )
              .then(
                (productId) => {
                  setBusy(false);
                  // Back to the form with the item already in a row.
                  setRows((before) =>
                    withSpare([
                      ...before.filter(used),
                      emptyRow({
                        // A Unit with one place gets it filled in too.
                        location:
                          mine.length === 1 && mine[0] !== undefined
                            ? keyOf(mine[0])
                            : "",
                        productId,
                        storage: keyOf(change.putIn),
                        quantity: change.quantity,
                      }),
                    ]),
                  );
                  back(pt(language, "np_saved", change.label));
                },
                (error: unknown) => {
                  setBusy(false);
                  setFailure(refusal(language, error));
                  void load(true);
                },
              );
          }}
          storage={storage}
        />
      )}
    </div>
  );
}

function InventoryForm({
  language,
  unitNumber,
  catalogue,
  mine,
  storage,
  rows,
  canMove,
  canBuy,
  canTakeOut,
  busy,
  failure,
  onRows,
  onSave,
  onBuy,
  onTakeOut,
  onClose,
}: {
  language: Language;
  unitNumber: string;
  catalogue: Catalogue;
  /** This Unit's places. */
  mine: Place[];
  /** The places of the Units not for rent (the warehouse). */
  storage: Place[];
  rows: Row[];
  canMove: boolean;
  canBuy: boolean;
  canTakeOut: boolean;
  busy: boolean;
  failure: string | null;
  onRows: (rows: Row[]) => void;
  onSave: (movements: NewMovement[], names: string) => void;
  onBuy: () => void;
  onTakeOut: (place: Place, productId: string) => void;
  onClose: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const products = new Map(
    catalogue.products.map((item) => [item.product_id, item]),
  );
  const stored = catalogue.products.filter(
    (item) =>
      item.kind === "ITEM" &&
      UNIT_CATEGORIES.has(item.category_code) &&
      storage.some((place) => held(place, item.product_id) > 0),
  );
  const shown = withSpare(rows);
  const byKey = new Map(
    [...mine, ...storage].map((place) => [keyOf(place), place]),
  );

  function change(key: number, patch: Partial<Row>) {
    setError(null);
    onRows(
      withSpare(
        shown.map((row) =>
          row.key === key
            ? {
                ...row,
                ...patch,
                // A new Item needs its own storage place.
                ...(patch.productId !== undefined ? { storage: "" } : {}),
              }
            : row,
        ),
      ),
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const filled = shown.filter(used);
    if (filled.length === 0) {
      setError(pt(language, "ui_nothing"));
      return;
    }
    const taken = new Map<string, number>();
    const movements: NewMovement[] = [];
    const names: string[] = [];
    for (const [index, row] of filled.entries()) {
      const product = products.get(row.productId);
      const target = byKey.get(row.location);
      const source = byKey.get(row.storage);
      const amount =
        product === undefined
          ? null
          : quantityFromText(row.quantity, product.measure_unit);
      if (
        product === undefined ||
        target === undefined ||
        source === undefined ||
        amount === null
      ) {
        setError(pt(language, "ui_row", index + 1, pt(language, "e_row")));
        return;
      }
      const sourceKey = `${keyOf(source)}|${product.product_id}`;
      const already = taken.get(sourceKey) ?? 0;
      const there = held(source, product.product_id);
      if (already + Number(amount) > there) {
        setError(
          pt(
            language,
            "ui_row",
            index + 1,
            pt(language, "e_row_short", there - already),
          ),
        );
        return;
      }
      taken.set(sourceKey, already + Number(amount));
      names.push(productName(product, language));
      movements.push({
        kind: "TRANSFER",
        product_id: product.product_id,
        quantity: amount,
        from: refOf(source),
        to: refOf(target),
        unit_cost_usd_cents: null,
        supplier: null,
        receipt_reference: null,
        reason: null,
      });
    }
    onSave(movements, names.join(", "));
  }

  const now = mine.flatMap((place) =>
    place.stock.map((line) => ({ place, line })),
  );
  return (
    <Dialog
      actions={
        canBuy ? (
          <button
            className="ui-btn"
            disabled={busy}
            onClick={onBuy}
            type="button"
          >
            <Icon name="plus" small />
            {pt(language, "sm_purchase")}
          </button>
        ) : undefined
      }
      busy={busy}
      closeLabel={pt(language, "close")}
      onClose={onClose}
      onSubmit={canMove ? submit : undefined}
      submitLabel={pt(language, "save")}
      title={pt(language, "ui_t", unitNumber)}
      wide
    >
      {canMove && (
        <fieldset className="ui-radios">
          <legend>{pt(language, "ui_put_in")}</legend>
          <p className="help">
            {stored.length === 0
              ? pt(language, "ui_none_in_storage")
              : pt(language, "ui_help")}
          </p>
          <div className="ui-tablewrap">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">{pt(language, "ui_location")}</th>
                  <th scope="col">{pt(language, "ui_item")}</th>
                  <th scope="col">{pt(language, "ui_storage")}</th>
                  <th scope="col">{pt(language, "sm_qty")}</th>
                  <th scope="col">
                    <span className="ui-sr">{pt(language, "pr_actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row, index) => {
                  const number = index + 1;
                  const sources = storage.filter(
                    (place) => held(place, row.productId) > 0,
                  );
                  return (
                    <tr key={row.key}>
                      <td>
                        <select
                          aria-label={`${pt(language, "ui_location")} ${String(number)}`}
                          onChange={(event) => {
                            change(row.key, {
                              location: event.currentTarget.value,
                            });
                          }}
                          value={row.location}
                        >
                          <option value="">{pt(language, "md_choose")}</option>
                          {mine.map((place) => (
                            <option key={keyOf(place)} value={keyOf(place)}>
                              {placeName(place, language)} {place.number}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          aria-label={`${pt(language, "ui_item")} ${String(number)}`}
                          onChange={(event) => {
                            change(row.key, {
                              productId: event.currentTarget.value,
                            });
                          }}
                          value={row.productId}
                        >
                          <option value="">{pt(language, "md_choose")}</option>
                          {stored.map((item) => (
                            <option
                              key={item.product_id}
                              value={item.product_id}
                            >
                              {item.sku} · {productName(item, language)}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          aria-label={`${pt(language, "ui_storage")} ${String(number)}`}
                          disabled={row.productId === ""}
                          onChange={(event) => {
                            change(row.key, {
                              storage: event.currentTarget.value,
                            });
                          }}
                          value={row.storage}
                        >
                          <option value="">{pt(language, "md_choose")}</option>
                          {sources.map((place) => (
                            <option key={keyOf(place)} value={keyOf(place)}>
                              {placeLabel(place, language)} (
                              {pt(
                                language,
                                "md_at_place",
                                held(place, row.productId),
                              )}
                              )
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          aria-label={`${pt(language, "sm_qty")} ${String(number)}`}
                          inputMode="numeric"
                          onChange={(event) => {
                            change(row.key, {
                              quantity: event.currentTarget.value,
                            });
                          }}
                          size={4}
                          value={row.quantity}
                        />
                      </td>
                      <td>
                        {used(row) && (
                          <button
                            aria-label={pt(language, "ui_remove", number)}
                            className="ui-btn"
                            onClick={() => {
                              setError(null);
                              onRows(
                                withSpare(
                                  shown.filter(
                                    (other) => other.key !== row.key,
                                  ),
                                ),
                              );
                            }}
                            type="button"
                          >
                            <Icon name="x" small />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </fieldset>
      )}
      <h3>{pt(language, "ui_now")}</h3>
      {now.length === 0 ? (
        <p className="ui-muted">{pt(language, "ui_empty")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{pt(language, "ui_location")}</th>
                <th scope="col">{pt(language, "ui_item")}</th>
                <th scope="col">{pt(language, "sm_qty")}</th>
                {canTakeOut && (
                  <th scope="col">
                    <span className="ui-sr">{pt(language, "pr_actions")}</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {now.map(({ place, line }) => {
                const item = products.get(line.product_id);
                const name =
                  item === undefined
                    ? line.name_en
                    : productName(item, language);
                const where = `${placeName(place, language)} ${String(place.number)}`;
                return (
                  <tr key={`${keyOf(place)}-${line.product_id}`}>
                    <td>{where}</td>
                    <td>
                      {line.sku} · {name}
                    </td>
                    <td className="ui-num">
                      {line.quantity} {unitName(line.measure_unit, language)}
                    </td>
                    {canTakeOut && (
                      <td>
                        <button
                          aria-label={`${pt(language, "ui_take_out")}: ${name}, ${where}`}
                          className="ui-btn"
                          disabled={busy}
                          onClick={() => {
                            onTakeOut(place, line.product_id);
                          }}
                          type="button"
                        >
                          {pt(language, "ui_take_out")}
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

function TakeOutDialog({
  language,
  place,
  product,
  storage,
  canMove,
  canAdjust,
  busy,
  failure,
  onBack,
  onSave,
}: {
  language: Language;
  place: Place;
  product: Product | null;
  storage: Place[];
  canMove: boolean;
  canAdjust: boolean;
  busy: boolean;
  failure: string | null;
  onBack: () => void;
  onSave: (movement: NewMovement, name: string) => void;
}) {
  const [way, setWay] = useState<"BACK" | "BROKEN">(
    canMove ? "BACK" : "BROKEN",
  );
  const [quantity, setQuantity] = useState("1");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const name = product === null ? "" : productName(product, language);
  const there = product === null ? 0 : held(place, product.product_id);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (product === null) return;
    const amount = quantityFromText(quantity, product.measure_unit);
    if (amount === null) {
      setError(
        pt(
          language,
          "e_qty",
          pt(
            language,
            WHOLE_UNITS.has(product.measure_unit)
              ? "e_qty_whole"
              : "e_qty_part",
          ),
        ),
      );
      return;
    }
    if (Number(amount) > there) {
      setError(pt(language, "e_short", there));
      return;
    }
    const target = storage.find((item) => keyOf(item) === to);
    if (way === "BACK" && target === undefined) {
      setError(pt(language, "e_place"));
      return;
    }
    if (reason.trim() === "") {
      setError(pt(language, "e_reason"));
      return;
    }
    onSave(
      {
        kind: way === "BACK" ? "TRANSFER" : "ADJUSTMENT_OUT",
        product_id: product.product_id,
        quantity: amount,
        from: refOf(place),
        to: way === "BACK" && target !== undefined ? refOf(target) : null,
        unit_cost_usd_cents: null,
        supplier: null,
        receipt_reference: null,
        reason: reason.trim(),
      },
      name,
    );
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "back")}
      onClose={onBack}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, "to_t", name)}
    >
      <p className="ui-muted">
        {pt(language, "to_from", placeLabel(place, language))} ·{" "}
        {pt(language, "md_at_place", there)}
      </p>
      <fieldset className="ui-radios">
        <legend>{pt(language, "md_way")}</legend>
        {(
          [
            ["BACK", "to_back", canMove],
            ["BROKEN", "to_broken", canAdjust],
          ] as const
        ).map(([choice, key, allowed]) => (
          <label className={allowed ? "ui-chk" : "ui-chk off"} key={choice}>
            <input
              checked={way === choice}
              disabled={!allowed}
              name="to-way"
              onChange={() => {
                setWay(choice);
                setError(null);
              }}
              type="radio"
            />
            <span>
              {pt(language, key)}
              {choice === "BROKEN" && !allowed && (
                <small className="ui-muted ui-sub2">
                  {pt(language, "to_broken_h")}
                </small>
              )}
            </span>
          </label>
        ))}
      </fieldset>
      <div className="ui-field">
        <label htmlFor="to-qty">
          {pt(language, "sm_qty")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <input
          id="to-qty"
          inputMode="decimal"
          onChange={(event) => {
            setQuantity(event.currentTarget.value);
            setError(null);
          }}
          value={quantity}
        />
      </div>
      {way === "BACK" && (
        <div className="ui-field">
          <label htmlFor="to-to">
            {pt(language, "md_put_in")}
            <span className="req">{pt(language, "required")}</span>
          </label>
          <select
            id="to-to"
            onChange={(event) => {
              setTo(event.currentTarget.value);
              setError(null);
            }}
            value={to}
          >
            <option value="">{pt(language, "md_choose")}</option>
            {storage.map((item) => (
              <option key={keyOf(item)} value={keyOf(item)}>
                {placeLabel(item, language)}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="to-reason">
          {pt(language, "md_reason")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <textarea
          id="to-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
            setError(null);
          }}
          rows={2}
          value={reason}
        />
      </div>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}

export interface PurchaseChange {
  /** null for a new product. */
  product: Product | null;
  nameEn: string;
  nameKh: string | null;
  category: string;
  label: string;
  quantity: string;
  cost: number;
  supplier: string | null;
  receipt: string | null;
  putIn: Place;
}

function PurchaseDialog({
  language,
  catalogue,
  storage,
  canAdd,
  busy,
  failure,
  onBack,
  onSave,
}: {
  language: Language;
  catalogue: Catalogue;
  storage: Place[];
  canAdd: boolean;
  busy: boolean;
  failure: string | null;
  onBack: () => void;
  onSave: (change: PurchaseChange) => void;
}) {
  const products = catalogue.products.filter(
    (item) =>
      item.kind === "ITEM" &&
      !item.discontinued &&
      UNIT_CATEGORIES.has(item.category_code),
  );
  const [kind, setKind] = useState<"REORDER" | "NEW">(
    products.length === 0 && canAdd ? "NEW" : "REORDER",
  );
  const [productId, setProductId] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameKh, setNameKh] = useState("");
  const [category, setCategory] = useState("FURNITURE");
  const [quantity, setQuantity] = useState("1");
  const [cost, setCost] = useState("");
  const [supplier, setSupplier] = useState("");
  const [receipt, setReceipt] = useState("");
  const [putIn, setPutIn] = useState("");
  const [error, setError] = useState<string | null>(null);
  const product =
    products.find((item) => item.product_id === productId) ?? null;
  const typedCost = centsFromText(cost);
  const step = catalogue.rules.price_round_up_usd_cents ?? 10;
  const categories = catalogue.categories.filter((item) =>
    UNIT_CATEGORIES.has(item.code),
  );

  function fail(key: ProductsTextKey) {
    setError(pt(language, key));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (kind === "REORDER" && product === null) {
      fail("e_product");
      return;
    }
    const english = nameEn.trim();
    if (kind === "NEW") {
      if (english === "" || english.length > 120) {
        fail("e_name");
        return;
      }
    }
    const unit = product?.measure_unit ?? "PIECE";
    const amount = quantityFromText(quantity, unit);
    if (amount === null) {
      setError(pt(language, "e_qty", pt(language, "e_qty_whole")));
      return;
    }
    if (typedCost === null || typedCost <= 0) {
      fail("e_money");
      return;
    }
    const place = storage.find((item) => keyOf(item) === putIn);
    if (place === undefined) {
      fail("e_place");
      return;
    }
    onSave({
      product: kind === "REORDER" ? product : null,
      nameEn: english,
      nameKh: nameKh.trim() === "" ? null : nameKh.trim(),
      category,
      label: product === null ? english : productName(product, language),
      quantity: amount,
      cost: typedCost,
      supplier: supplier.trim() === "" ? null : supplier.trim(),
      receipt: receipt.trim() === "" ? null : receipt.trim(),
      putIn: place,
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "back")}
      onClose={onBack}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, "np_t")}
    >
      {canAdd && (
        <fieldset className="ui-radios">
          <legend>{pt(language, "np_kind")}</legend>
          {(
            [
              ["REORDER", "np_reorder"],
              ["NEW", "np_new"],
            ] as const
          ).map(([choice, key]) => (
            <label className="ui-chk" key={choice}>
              <input
                checked={kind === choice}
                name="np-kind"
                onChange={() => {
                  setKind(choice);
                  setError(null);
                }}
                type="radio"
              />
              <span>{pt(language, key)}</span>
            </label>
          ))}
        </fieldset>
      )}
      {kind === "REORDER" ? (
        <div className="ui-field">
          <label htmlFor="np-product">
            {pt(language, "sm_product")}
            <span className="req">{pt(language, "required")}</span>
          </label>
          <select
            id="np-product"
            onChange={(event) => {
              const chosen = products.find(
                (item) => item.product_id === event.currentTarget.value,
              );
              setProductId(event.currentTarget.value);
              // The last cost is filled in.
              if (chosen?.cost_usd_cents != null) {
                setCost((chosen.cost_usd_cents / 100).toFixed(2));
              }
              setError(null);
            }}
            value={productId}
          >
            <option value="">{pt(language, "md_choose")}</option>
            {products.map((item) => (
              <option key={item.product_id} value={item.product_id}>
                {item.sku} · {productName(item, language)}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <>
          <div className="ui-field">
            <label htmlFor="np-name">
              {pt(language, "pd_name_en")}
              <span className="req">{pt(language, "required")}</span>
            </label>
            <input
              autoComplete="off"
              id="np-name"
              maxLength={120}
              onChange={(event) => {
                setNameEn(event.currentTarget.value);
                setError(null);
              }}
              value={nameEn}
            />
          </div>
          <div className="ui-field">
            <label htmlFor="np-name-kh">{pt(language, "pd_name_kh")}</label>
            <input
              autoComplete="off"
              id="np-name-kh"
              lang="km"
              maxLength={120}
              onChange={(event) => {
                setNameKh(event.currentTarget.value);
              }}
              value={nameKh}
            />
          </div>
          <div className="ui-field">
            <label htmlFor="np-category">{pt(language, "pr_category")}</label>
            <select
              id="np-category"
              onChange={(event) => {
                setCategory(event.currentTarget.value);
              }}
              value={category}
            >
              {categories.map((item) => (
                <option key={item.code} value={item.code}>
                  {language === "km" && item.name_kh !== null
                    ? item.name_kh
                    : item.name_en}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
      <div className="ui-field">
        <label htmlFor="np-qty">
          {pt(language, "sm_qty")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <input
          id="np-qty"
          inputMode="numeric"
          onChange={(event) => {
            setQuantity(event.currentTarget.value);
            setError(null);
          }}
          value={quantity}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="np-cost">
          {pt(language, "md_unit_cost")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <input
          id="np-cost"
          inputMode="decimal"
          onChange={(event) => {
            setCost(event.currentTarget.value);
            setError(null);
          }}
          placeholder="0.00"
          value={cost}
        />
        {product !== null && typedCost !== null && typedCost > 0 && (
          <p className="help">
            {pt(
              language,
              "md_price_h",
              dollars(product.price_usd_cents),
              percent(product.mark_up_basis_points),
              dollars(priceFor(typedCost, product.mark_up_basis_points, step)),
            )}
          </p>
        )}
      </div>
      <div className="ui-field">
        <label htmlFor="np-supplier">{pt(language, "md_supplier")}</label>
        <input
          autoComplete="off"
          id="np-supplier"
          maxLength={200}
          onChange={(event) => {
            setSupplier(event.currentTarget.value);
          }}
          value={supplier}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="np-receipt">{pt(language, "md_receipt")}</label>
        <input
          autoComplete="off"
          id="np-receipt"
          maxLength={100}
          onChange={(event) => {
            setReceipt(event.currentTarget.value);
          }}
          value={receipt}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="np-put-in">
          {pt(language, "md_put_in")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        {storage.length === 0 ? (
          <p className="help">{pt(language, "np_no_storage")}</p>
        ) : (
          <select
            aria-describedby="np-put-in-h"
            id="np-put-in"
            onChange={(event) => {
              setPutIn(event.currentTarget.value);
              setError(null);
            }}
            value={putIn}
          >
            <option value="">{pt(language, "md_choose")}</option>
            {storage.map((item) => (
              <option key={keyOf(item)} value={keyOf(item)}>
                {placeLabel(item, language)}
              </option>
            ))}
          </select>
        )}
        <p className="help" id="np-put-in-h">
          {pt(language, "np_put_in_h")}
        </p>
      </div>
      <Failure text={error ?? failure} />
    </Dialog>
  );
}
