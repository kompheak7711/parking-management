// V1.1 part 4 (DL-121): the stock dialogs of Building › Products: New purchase, Move stock,
// Adjust stock (Manager or Owner) and Add place. The server checks the stock again and refuses a
// movement that would take a place below 0.

import { type FormEvent, useState } from "react";

import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  type Catalogue,
  centsFromText,
  dollars,
  type Locations,
  type NewMovement,
  type Place,
  type PlaceKind,
  type PlaceRef,
  percent,
  priceFor,
  quantityFromText,
  WHOLE_UNITS,
} from "./productsClient";
import { productName } from "./ProductDialogs";
import { pt, unitName } from "./text";

export type MovementMode = "PURCHASE" | "TRANSFER" | "ADJUST";

export function placeName(
  place: { name_en: string; name_kh: string | null },
  language: Language,
): string {
  return language === "km" && place.name_kh !== null
    ? place.name_kh
    : place.name_en;
}

/** "W01 · Cabinet 1". */
export function placeLabel(place: Place, language: Language): string {
  return `${place.unit_number} · ${placeName(place, language)} ${String(place.number)}`;
}

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

function held(place: Place, productId: string): string | null {
  return (
    place.stock.find((line) => line.product_id === productId)?.quantity ?? null
  );
}

function PlaceSelect({
  id,
  label,
  language,
  places,
  productId,
  value,
  onChange,
}: {
  id: string;
  label: string;
  language: Language;
  places: Place[];
  productId: string;
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="ui-field">
      <label htmlFor={id}>
        {label}
        <span className="req">{pt(language, "required")}</span>
      </label>
      <select
        id={id}
        onChange={(event) => {
          onChange(event.currentTarget.value);
        }}
        value={value}
      >
        <option value="">{pt(language, "md_choose")}</option>
        {places.map((place) => {
          const quantity = held(place, productId);
          return (
            <option key={keyOf(place)} value={keyOf(place)}>
              {placeLabel(place, language)}
              {quantity === null
                ? ""
                : ` (${pt(language, "md_at_place", quantity)})`}
            </option>
          );
        })}
      </select>
    </div>
  );
}

export function MovementDialog({
  language,
  mode,
  catalogue,
  locations,
  busy,
  failure,
  onClose,
  onSave,
}: {
  language: Language;
  mode: MovementMode;
  catalogue: Catalogue;
  locations: Locations;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSave: (movement: NewMovement) => void;
}) {
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [way, setWay] = useState<"IN" | "OUT">("OUT");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [cost, setCost] = useState("");
  const [supplier, setSupplier] = useState("");
  const [receipt, setReceipt] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const items = catalogue.products.filter(
    (product) =>
      product.kind === "ITEM" &&
      (mode === "PURCHASE"
        ? !product.discontinued
        : mode === "TRANSFER" || way === "OUT"
          ? Number(product.stock) > 0
          : true),
  );
  const product = items.find((item) => item.product_id === productId) ?? null;
  const takes = mode === "TRANSFER" || (mode === "ADJUST" && way === "OUT");
  const puts = mode !== "ADJUST" || way === "IN";
  const sources = locations.places.filter(
    (place) => held(place, productId) !== null,
  );
  const byKey = new Map(locations.places.map((place) => [keyOf(place), place]));
  const typedCost = centsFromText(cost);
  const step = catalogue.rules.price_round_up_usd_cents ?? 10;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (product === null) {
      setError(pt(language, "e_product"));
      return;
    }
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
    const source = takes ? (byKey.get(from) ?? null) : null;
    const target = puts ? (byKey.get(to) ?? null) : null;
    if ((takes && source === null) || (puts && target === null)) {
      setError(pt(language, "e_place"));
      return;
    }
    if (source !== null && target !== null && keyOf(source) === keyOf(target)) {
      setError(pt(language, "e_same"));
      return;
    }
    if (source !== null) {
      const there = held(source, product.product_id) ?? "0";
      if (Number(amount) > Number(there)) {
        setError(pt(language, "e_short", there));
        return;
      }
    }
    if (mode === "PURCHASE" && (typedCost === null || typedCost <= 0)) {
      setError(pt(language, "e_money"));
      return;
    }
    if (mode === "ADJUST" && reason.trim() === "") {
      setError(pt(language, "e_reason"));
      return;
    }
    const purchase = mode === "PURCHASE";
    onSave({
      kind:
        mode === "ADJUST"
          ? way === "IN"
            ? "ADJUSTMENT_IN"
            : "ADJUSTMENT_OUT"
          : mode,
      product_id: product.product_id,
      quantity: amount,
      from: source === null ? null : refOf(source),
      to: target === null ? null : refOf(target),
      unit_cost_usd_cents: purchase ? typedCost : null,
      supplier: purchase && supplier.trim() !== "" ? supplier.trim() : null,
      receipt_reference:
        purchase && receipt.trim() !== "" ? receipt.trim() : null,
      reason: !purchase && reason.trim() !== "" ? reason.trim() : null,
    });
  }

  const title =
    mode === "PURCHASE"
      ? "md_purchase_t"
      : mode === "TRANSFER"
        ? "md_transfer_t"
        : "md_adjust_t";
  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, title)}
    >
      {mode === "ADJUST" && (
        <fieldset className="ui-radios">
          <legend>{pt(language, "md_way")}</legend>
          {(["OUT", "IN"] as const).map((choice) => (
            <label className="ui-chk" key={choice}>
              <input
                checked={way === choice}
                name="md-way"
                onChange={() => {
                  setWay(choice);
                  setProductId("");
                  setFrom("");
                  setTo("");
                  setError(null);
                }}
                type="radio"
              />
              <span>{pt(language, choice === "IN" ? "md_in" : "md_out")}</span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="ui-field">
        <label htmlFor="md-product">
          {pt(language, "sm_product")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <select
          id="md-product"
          onChange={(event) => {
            setProductId(event.currentTarget.value);
            setFrom("");
            setError(null);
          }}
          value={productId}
        >
          <option value="">{pt(language, "md_choose")}</option>
          {items.map((item) => (
            <option key={item.product_id} value={item.product_id}>
              {item.sku} · {productName(item, language)}
            </option>
          ))}
        </select>
      </div>
      <div className="ui-field">
        <label htmlFor="md-qty">
          {pt(language, "sm_qty")}
          {product !== null && ` (${unitName(product.measure_unit, language)})`}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <input
          id="md-qty"
          inputMode="decimal"
          onChange={(event) => {
            setQuantity(event.currentTarget.value);
            setError(null);
          }}
          value={quantity}
        />
      </div>
      {takes && (
        <PlaceSelect
          id="md-from"
          label={pt(language, mode === "TRANSFER" ? "md_from" : "md_take_from")}
          language={language}
          onChange={(key) => {
            setFrom(key);
            setError(null);
          }}
          places={sources}
          productId={productId}
          value={from}
        />
      )}
      {puts && (
        <PlaceSelect
          id="md-to"
          label={pt(language, mode === "TRANSFER" ? "md_to" : "md_put_in")}
          language={language}
          onChange={(key) => {
            setTo(key);
            setError(null);
          }}
          places={locations.places}
          productId={productId}
          value={to}
        />
      )}
      {mode === "PURCHASE" && (
        <>
          <div className="ui-field">
            <label htmlFor="md-cost">
              {pt(language, "md_unit_cost")}
              <span className="req">{pt(language, "required")}</span>
            </label>
            <input
              aria-describedby={product === null ? undefined : "md-cost-h"}
              id="md-cost"
              inputMode="decimal"
              onChange={(event) => {
                setCost(event.currentTarget.value);
                setError(null);
              }}
              placeholder={
                product?.cost_usd_cents == null
                  ? "0.00"
                  : (product.cost_usd_cents / 100).toFixed(2)
              }
              value={cost}
            />
            {product !== null && typedCost !== null && typedCost > 0 && (
              <p className="help" id="md-cost-h">
                {pt(
                  language,
                  "md_price_h",
                  dollars(product.price_usd_cents),
                  percent(product.mark_up_basis_points),
                  dollars(
                    priceFor(typedCost, product.mark_up_basis_points, step),
                  ),
                )}
              </p>
            )}
          </div>
          <div className="ui-field">
            <label htmlFor="md-supplier">{pt(language, "md_supplier")}</label>
            <input
              autoComplete="off"
              id="md-supplier"
              maxLength={200}
              onChange={(event) => {
                setSupplier(event.currentTarget.value);
              }}
              value={supplier}
            />
          </div>
          <div className="ui-field">
            <label htmlFor="md-receipt">{pt(language, "md_receipt")}</label>
            <input
              autoComplete="off"
              id="md-receipt"
              maxLength={100}
              onChange={(event) => {
                setReceipt(event.currentTarget.value);
              }}
              value={receipt}
            />
          </div>
        </>
      )}
      {mode !== "PURCHASE" && (
        <div className="ui-field">
          <label htmlFor="md-reason">
            {pt(language, "md_reason")}
            <span className="req">
              {pt(language, mode === "ADJUST" ? "required" : "optional")}
            </span>
          </label>
          <textarea
            id="md-reason"
            maxLength={500}
            onChange={(event) => {
              setReason(event.currentTarget.value);
              setError(null);
            }}
            rows={2}
            value={reason}
          />
        </div>
      )}
      {(error ?? failure) !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{error ?? failure}</span>
        </p>
      )}
    </Dialog>
  );
}

export function AddPlaceDialog({
  language,
  unitNumber,
  places,
  kinds,
  busy,
  failure,
  onClose,
  onSave,
}: {
  language: Language;
  unitNumber: string;
  /** The places this Unit has now. */
  places: Place[];
  kinds: PlaceKind[];
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSave: (itemId: string) => void;
}) {
  const [itemId, setItemId] = useState(kinds[0]?.item_id ?? "");
  const kind = kinds.find((item) => item.item_id === itemId) ?? null;
  const next = places.filter((place) => place.item_id === itemId).length + 1;
  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        if (itemId !== "") onSave(itemId);
      }}
      submitLabel={pt(language, "save")}
      title={pt(language, "ap_t", unitNumber)}
    >
      <div className="ui-field">
        <label htmlFor="ap-kind">{pt(language, "ap_kind")}</label>
        <select
          id="ap-kind"
          onChange={(event) => {
            setItemId(event.currentTarget.value);
          }}
          value={itemId}
        >
          {kinds.map((item) => (
            <option key={item.item_id} value={item.item_id}>
              {placeName(item, language)}
            </option>
          ))}
        </select>
      </div>
      {kind !== null && (
        <p className="ui-muted" role="status">
          {pt(
            language,
            "ap_next",
            `${unitNumber} · ${placeName(kind, language)} ${String(next)}`,
          )}
        </p>
      )}
      {failure !== null && (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{failure}</span>
        </p>
      )}
    </Dialog>
  );
}
