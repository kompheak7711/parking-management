// V1.1 part 4 (DL-121): the product dialogs of Building › Products: Add and Edit product, the
// mark-ups (Owner by default), a Service's cost and the price history.

import { type FormEvent, useEffect, useState } from "react";

import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import {
  basisPointsFromText,
  type Catalogue,
  centsFromText,
  dollars,
  ITEM_UNITS,
  type MarkUps,
  type NewProduct,
  percent,
  type PriceChange,
  priceFor,
  type Product,
  type ProductFields,
  type ProductsApi,
  SERVICE_UNITS,
} from "./productsClient";
import { pt, unitName } from "./text";

export function productName(product: Product, language: Language): string {
  return language === "km" && product.name_kh !== null
    ? product.name_kh
    : product.name_en;
}

export function categoryName(
  catalogue: Catalogue,
  code: string,
  language: Language,
): string {
  const found = catalogue.categories.find((item) => item.code === code);
  if (found === undefined) return code;
  return language === "km" && found.name_kh !== null
    ? found.name_kh
    : found.name_en;
}

function FieldError({ text }: { text: string | null }) {
  if (text === null) return null;
  return (
    <p className="ui-error" role="alert">
      <Icon name="alert" small />
      <span>{text}</span>
    </p>
  );
}

function wholeOrNull(typed: string): number | null | "bad" {
  const value = typed.trim();
  if (value === "") return null;
  return /^\d{1,7}$/.test(value) ? Number(value) : "bad";
}

export function ProductDialog({
  language,
  catalogue,
  product,
  busy,
  failure,
  onClose,
  onAdd,
  onChange,
}: {
  language: Language;
  catalogue: Catalogue;
  /** null for a new product. */
  product: Product | null;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onAdd: (product: NewProduct) => void;
  onChange: (
    product: Product,
    change: ProductFields & { discontinued: boolean },
  ) => void;
}) {
  const [nameEn, setNameEn] = useState(product?.name_en ?? "");
  const [nameKh, setNameKh] = useState(product?.name_kh ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [category, setCategory] = useState(
    product?.category_code ?? catalogue.categories[0]?.code ?? "",
  );
  const kind =
    catalogue.categories.find((item) => item.code === category)?.kind ?? "ITEM";
  const units: readonly string[] =
    kind === "SERVICE" ? SERVICE_UNITS : ITEM_UNITS;
  const [unit, setUnit] = useState(product?.measure_unit ?? "PIECE");
  const [level, setLevel] = useState(
    product?.reorder_level === null || product === null
      ? ""
      : String(product.reorder_level),
  );
  const [quantity, setQuantity] = useState(
    product?.reorder_quantity === null || product === null
      ? ""
      : String(product.reorder_quantity),
  );
  const [cost, setCost] = useState("");
  const [discontinued, setDiscontinued] = useState(
    product?.discontinued ?? false,
  );
  const [error, setError] = useState<string | null>(null);
  const shownUnit = units.includes(unit) ? unit : (units[0] ?? "PIECE");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const english = nameEn.trim();
    if (english === "" || english.length > 120) {
      setError(pt(language, "e_name"));
      return;
    }
    const reorderLevel = kind === "SERVICE" ? null : wholeOrNull(level);
    const reorderQuantity = kind === "SERVICE" ? null : wholeOrNull(quantity);
    if (
      reorderLevel === "bad" ||
      reorderQuantity === "bad" ||
      reorderQuantity === 0
    ) {
      setError(pt(language, "e_whole"));
      return;
    }
    const fields: ProductFields = {
      name_en: english,
      name_kh: nameKh.trim() === "" ? null : nameKh.trim(),
      description: description.trim() === "" ? null : description.trim(),
      category_code: category,
      measure_unit: shownUnit,
      reorder_level: reorderLevel,
      reorder_quantity: reorderQuantity,
    };
    if (product !== null) {
      onChange(product, { ...fields, discontinued });
      return;
    }
    let serviceCost: number | null = null;
    if (kind === "SERVICE") {
      serviceCost = centsFromText(cost);
      if (serviceCost === null || serviceCost <= 0) {
        setError(pt(language, "e_money"));
        return;
      }
    }
    onAdd({ ...fields, service_cost_usd_cents: serviceCost });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={
        product === null
          ? pt(language, "pd_new_t")
          : pt(language, "pd_edit_t", product.sku)
      }
    >
      <div className="ui-field">
        <label htmlFor="pd-name">
          {pt(language, "pd_name_en")}
          <span className="req">{pt(language, "required")}</span>
        </label>
        <input
          autoComplete="off"
          id="pd-name"
          maxLength={120}
          onChange={(event) => {
            setNameEn(event.currentTarget.value);
            setError(null);
          }}
          value={nameEn}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="pd-name-kh">{pt(language, "pd_name_kh")}</label>
        <input
          autoComplete="off"
          id="pd-name-kh"
          lang="km"
          maxLength={120}
          onChange={(event) => {
            setNameKh(event.currentTarget.value);
          }}
          value={nameKh}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="pd-description">{pt(language, "pd_description")}</label>
        <textarea
          id="pd-description"
          maxLength={500}
          onChange={(event) => {
            setDescription(event.currentTarget.value);
          }}
          rows={2}
          value={description}
        />
      </div>
      <div className="ui-field">
        <label htmlFor="pd-category">{pt(language, "pr_category")}</label>
        <select
          id="pd-category"
          onChange={(event) => {
            setCategory(event.currentTarget.value);
          }}
          value={category}
        >
          {catalogue.categories
            .filter(
              (item) =>
                product === null ||
                item.kind === product.kind ||
                item.code === product.category_code,
            )
            .map((item) => (
              <option key={item.code} value={item.code}>
                {categoryName(catalogue, item.code, language)}
              </option>
            ))}
        </select>
      </div>
      <div className="ui-field">
        <label htmlFor="pd-unit">{pt(language, "pr_unit")}</label>
        <select
          id="pd-unit"
          onChange={(event) => {
            setUnit(event.currentTarget.value);
          }}
          value={shownUnit}
        >
          {units.map((item) => (
            <option key={item} value={item}>
              {unitName(item, language)}
            </option>
          ))}
        </select>
      </div>
      {kind === "ITEM" ? (
        <>
          <div className="ui-field">
            <label htmlFor="pd-level">{pt(language, "pd_reorder_level")}</label>
            <input
              aria-describedby="pd-level-h"
              id="pd-level"
              inputMode="numeric"
              onChange={(event) => {
                setLevel(event.currentTarget.value);
                setError(null);
              }}
              value={level}
            />
            <p className="help" id="pd-level-h">
              {pt(language, "pd_reorder_h")}
            </p>
          </div>
          <div className="ui-field">
            <label htmlFor="pd-qty">{pt(language, "pd_reorder_qty")}</label>
            <input
              id="pd-qty"
              inputMode="numeric"
              onChange={(event) => {
                setQuantity(event.currentTarget.value);
                setError(null);
              }}
              value={quantity}
            />
          </div>
          {product === null && (
            <p className="help">{pt(language, "pd_item_cost_h")}</p>
          )}
        </>
      ) : (
        product === null && (
          <div className="ui-field">
            <label htmlFor="pd-cost">
              {pt(language, "pd_service_cost")}
              <span className="req">{pt(language, "required")}</span>
            </label>
            <input
              aria-describedby="pd-cost-h"
              id="pd-cost"
              inputMode="decimal"
              onChange={(event) => {
                setCost(event.currentTarget.value);
                setError(null);
              }}
              placeholder="0.00"
              value={cost}
            />
            <p className="help" id="pd-cost-h">
              {pt(language, "pd_service_cost_h")}
            </p>
          </div>
        )
      )}
      {product !== null && (
        <label className="ui-chk">
          <input
            aria-describedby="pd-disc-h"
            checked={discontinued}
            onChange={(event) => {
              setDiscontinued(event.currentTarget.checked);
            }}
            type="checkbox"
          />
          <span>
            {pt(language, "pr_discontinued")}
            <small className="ui-muted ui-sub2" id="pd-disc-h">
              {pt(language, "pd_discontinued_h")}
            </small>
          </span>
        </label>
      )}
      <FieldError text={error ?? failure} />
    </Dialog>
  );
}

export function MarkUpDialog({
  language,
  catalogue,
  product,
  busy,
  failure,
  onClose,
  onSave,
}: {
  language: Language;
  catalogue: Catalogue;
  product: Product;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSave: (change: MarkUps) => void;
}) {
  const input = (points: number | null) =>
    points === null ? "" : String(points / 100);
  const [markUp, setMarkUp] = useState(input(product.mark_up_basis_points));
  const [minimum, setMinimum] = useState(
    input(product.min_mark_up_basis_points),
  );
  const [maximum, setMaximum] = useState(
    input(product.max_mark_up_basis_points),
  );
  const [error, setError] = useState<string | null>(null);
  const typed = basisPointsFromText(markUp);
  const step = catalogue.rules.price_round_up_usd_cents ?? 10;
  const preview =
    typed !== null && product.cost_usd_cents !== null
      ? priceFor(product.cost_usd_cents, typed, step)
      : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const low = basisPointsFromText(minimum);
    const high = maximum.trim() === "" ? null : basisPointsFromText(maximum);
    if (
      typed === null ||
      low === null ||
      (maximum.trim() !== "" && high === null)
    ) {
      setError(pt(language, "e_percent"));
      return;
    }
    if (typed < low || (high !== null && typed > high)) {
      setError(pt(language, "mu_range"));
      return;
    }
    onSave({
      mark_up_basis_points: typed,
      min_mark_up_basis_points: low,
      max_mark_up_basis_points: high,
    });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, "mu_t", productName(product, language))}
    >
      {(
        [
          ["mu-mark-up", "mu_mark_up", markUp, setMarkUp],
          ["mu-min", "mu_min", minimum, setMinimum],
          ["mu-max", "mu_max", maximum, setMaximum],
        ] as const
      ).map(([id, key, value, set]) => (
        <div className="ui-field" key={id}>
          <label htmlFor={id}>{pt(language, key)}</label>
          <input
            aria-describedby={id === "mu-max" ? "mu-max-h" : undefined}
            id={id}
            inputMode="decimal"
            onChange={(event) => {
              set(event.currentTarget.value);
              setError(null);
            }}
            value={value}
          />
          {id === "mu-max" && (
            <p className="help" id="mu-max-h">
              {pt(language, "mu_max_h")}
            </p>
          )}
        </div>
      ))}
      {preview !== null && (
        <p className="ui-muted" role="status">
          {pt(language, "mu_preview", dollars(preview))}
        </p>
      )}
      <FieldError text={error ?? failure} />
    </Dialog>
  );
}

export function ServiceCostDialog({
  language,
  product,
  busy,
  failure,
  onClose,
  onSave,
}: {
  language: Language;
  product: Product;
  busy: boolean;
  failure: string | null;
  onClose: () => void;
  onSave: (cents: number) => void;
}) {
  const [cost, setCost] = useState(
    product.cost_usd_cents === null
      ? ""
      : (product.cost_usd_cents / 100).toFixed(2),
  );
  const [error, setError] = useState<string | null>(null);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cents = centsFromText(cost);
    if (cents === null || cents <= 0) {
      setError(pt(language, "e_money"));
      return;
    }
    onSave(cents);
  }
  return (
    <Dialog
      busy={busy}
      closeLabel={pt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={pt(language, "save")}
      title={pt(language, "sc_t", productName(product, language))}
    >
      <div className="ui-field">
        <label htmlFor="sc-cost">{pt(language, "pd_service_cost")}</label>
        <input
          aria-describedby="sc-cost-h"
          id="sc-cost"
          inputMode="decimal"
          onChange={(event) => {
            setCost(event.currentTarget.value);
            setError(null);
          }}
          value={cost}
        />
        <p className="help" id="sc-cost-h">
          {pt(language, "pd_service_cost_h")}
        </p>
      </div>
      <FieldError text={error ?? failure} />
    </Dialog>
  );
}

export function PriceHistoryDialog({
  language,
  api,
  propertyId,
  product,
  onClose,
}: {
  language: Language;
  api: ProductsApi;
  propertyId: string;
  product: Product;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<PriceChange[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    api.prices(propertyId, product.product_id).then(
      (found) => {
        if (live) setRows(found);
      },
      () => {
        if (live) setFailed(true);
      },
    );
    return () => {
      live = false;
    };
  }, [api, product.product_id, propertyId]);
  return (
    <Dialog
      closeLabel={pt(language, "close")}
      onClose={onClose}
      title={pt(language, "ph_t", productName(product, language))}
      wide
    >
      {failed ? (
        <p className="ui-error" role="alert">
          <Icon name="alert" small />
          <span>{pt(language, "failed")}</span>
        </p>
      ) : rows === null ? (
        <p className="ui-muted" role="status">
          {pt(language, "loading")}
        </p>
      ) : rows.length === 0 ? (
        <p className="ui-muted">{pt(language, "ph_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th scope="col">{pt(language, "ph_when")}</th>
                <th scope="col">{pt(language, "ph_cause")}</th>
                <th scope="col">{pt(language, "pr_cost")}</th>
                <th scope="col">{pt(language, "pr_mark_up")}</th>
                <th scope="col">{pt(language, "pr_price")}</th>
                <th scope="col">{pt(language, "ph_by")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.created_at}-${String(index)}`}>
                  <td>{momentText(row.created_at)}</td>
                  <td>{pt(language, `ph_${row.cause}`)}</td>
                  <td className="ui-num">{dollars(row.cost_usd_cents)}</td>
                  <td className="ui-num">
                    {percent(row.mark_up_basis_points)}
                  </td>
                  <td className="ui-num">
                    <b>{dollars(row.price_usd_cents)}</b>
                  </td>
                  <td>{row.created_by_name ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Dialog>
  );
}
