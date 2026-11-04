// V1.1 part 6 (DL-123): New Quotation (mock-up round 16 "Create Quotation"). The Customer (one
// with a signed Lease), a line table of products with the price from Products, a note, and Save
// and print. The price box can be lowered only by a person with "Lower a price on a Quotation",
// never above the list price, and a lower price needs its reason. "#/quotations/new:<id>"
// starts from another Quotation: a waiting one is replaced by the new version (same Customer).

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { centsOf } from "../invoices/invoicesData";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import type {
  Catalogue,
  Product,
  ProductsApi,
} from "../products/productsClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { openPageInAddress } from "../shell/useHashPage";
import type { Language } from "../signInText";
import {
  type Quotation,
  QuotationsError,
  type QuotationsApi,
} from "./quotationsClient";
import { qt, type QuotationsTextKey } from "./text";

/** At most 20 lines on one Quotation, each a whole quantity from 1 to 999 (DB-QT-001). */
const MAX_LINES = 20;

interface Row {
  key: string;
  product: string;
  quantity: string;
  price: string;
}

interface CustomerChoice {
  id: string;
  name: string;
  unit: string;
  lease: string;
}

type Field = "cust" | "items" | "up" | "low";

const IDS: Record<Field, string> = {
  cust: "nq-cust",
  items: "nq-items",
  up: "nq-items",
  low: "nq-low",
};

const ERRORS: Record<Field, QuotationsTextKey> = {
  cust: "e_cust",
  items: "e_items",
  up: "e_up",
  low: "e_low_reason",
};

function blankRow(): Row {
  return { key: crypto.randomUUID(), product: "", quantity: "1", price: "" };
}

/** "15.00" for 1500 cents, the way the price box reads it. */
function priceText(value: number): string {
  return `${String(Math.floor(value / 100))}.${String(value % 100).padStart(2, "0")}`;
}

function quantityOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,3}$/.test(value)) return null;
  const number = Number(value);
  return number >= 1 && number <= 999 ? number : null;
}

// More pages than this means something is wrong; V1 has one building of a few dozen Units.
const MAX_PAGES = 100;

async function allLeases(
  api: Pick<LeaseApi, "list">,
  propertyId: string,
): Promise<LeaseResource[]> {
  const items: LeaseResource[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await api.list(
      propertyId,
      cursor === undefined ? {} : { cursor },
    );
    items.push(...result.items);
    if (result.next_cursor === null) return items;
    cursor = result.next_cursor;
  }
  throw new Error("Too many pages");
}

/** Each Customer with a signed Lease, with the Unit of their newest one. */
function customersOf(leases: LeaseResource[]): CustomerChoice[] {
  const chosen = new Map<string, CustomerChoice>();
  const byStart = [...leases].sort((left, right) =>
    (left.start_date ?? "").localeCompare(right.start_date ?? ""),
  );
  for (const lease of byStart) {
    if (lease.status === "DRAFTED" || lease.status === "CANCELLED") continue;
    chosen.set(lease.primary_tenant_id, {
      id: lease.primary_tenant_id,
      name: lease.primary_tenant_name,
      unit: lease.unit_number,
      lease: lease.lease_id,
    });
  }
  return [...chosen.values()].sort(
    (left, right) =>
      left.unit.localeCompare(right.unit, undefined, { numeric: true }) ||
      left.name.localeCompare(right.name),
  );
}

/** A product can be quoted when it has a price and is not a discontinued Service. */
function quotable(product: Product): boolean {
  return (
    product.price_usd_cents !== null &&
    !(product.kind === "SERVICE" && product.discontinued)
  );
}

interface Loaded {
  catalogue: Catalogue;
  customers: CustomerChoice[];
  from: Quotation | null;
}

export function NewQuotationForm({
  language,
  propertyId,
  api,
  productsApi,
  leaseApi,
  mayLower,
  fromId,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: QuotationsApi;
  productsApi: Pick<ProductsApi, "catalogue">;
  leaseApi: Pick<LeaseApi, "list">;
  /** "Lower a price on a Quotation" (Manager and Owner). */
  mayLower: boolean;
  /** Start from this Quotation; a waiting one is replaced. */
  fromId: string | null;
  onSaved: (made: Quotation) => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void Promise.all([
      productsApi.catalogue(propertyId),
      allLeases(leaseApi, propertyId).catch((): LeaseResource[] => []),
      fromId === null ? Promise.resolve(null) : api.get(propertyId, fromId),
    ])
      .then(([catalogue, leases, from]) => {
        if (operation === sequence.current)
          setLoaded({ catalogue, customers: customersOf(leases), from });
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, fromId, leaseApi, productsApi, propertyId]);

  useEffect(() => {
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        if (fromId === null) openPageInAddress("quotations");
        else openPageInAddress("quotations", false, `qt:${fromId}`);
      }}
      type="button"
    >
      <Icon name="back" small />
      {qt(language, "back")}
    </button>
  );
  if (failed)
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{qt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {qt(language, "retry")}
          </button>
        </div>
      </>
    );
  if (loaded === null)
    return (
      <>
        {back}
        <p className="ui-muted" role="status">
          {qt(language, "loading")}
        </p>
      </>
    );
  return (
    <Form
      api={api}
      back={back}
      language={language}
      loaded={loaded}
      mayLower={mayLower}
      onSaved={onSaved}
      propertyId={propertyId}
    />
  );
}

function Form({
  language,
  propertyId,
  api,
  loaded,
  mayLower,
  back,
  onSaved,
}: {
  language: Language;
  propertyId: string;
  api: QuotationsApi;
  loaded: Loaded;
  mayLower: boolean;
  back: ReactNode;
  onSaved: (made: Quotation) => void;
}) {
  const { catalogue, from } = loaded;
  const replacing = from !== null && from.state === "WAITING" ? from : null;
  const products = new Map(
    catalogue.products.map((product) => [product.product_id, product]),
  );
  const customers = [...loaded.customers];
  // The Customer of the Quotation it starts from stays on the list.
  if (
    from !== null &&
    !customers.some((entry) => entry.id === from.customer_id)
  )
    customers.push({
      id: from.customer_id,
      name: from.customer_name,
      unit: from.unit_number ?? "",
      lease: from.lease_id ?? "",
    });
  const [customer, setCustomer] = useState(from?.customer_id ?? "");
  const [rows, setRows] = useState<Row[]>(() => {
    const start =
      from?.lines
        .filter((line) => products.has(line.product_id))
        .map((line) => ({
          key: crypto.randomUUID(),
          product: line.product_id,
          quantity: String(line.quantity),
          price: priceText(
            Math.min(
              line.price_usd_cents,
              products.get(line.product_id)?.price_usd_cents ??
                line.price_usd_cents,
            ),
          ),
        })) ?? [];
    return [...start, blankRow()];
  });
  const [note, setNote] = useState(from?.note ?? "");
  const [lowReason, setLowReason] = useState("");
  const [problems, setProblems] = useState<Field[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const summary = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (problems !== null && problems.length > 0) summary.current?.focus();
  }, [problems]);

  const chosen = customers.find((entry) => entry.id === customer);
  const values = rows.map((row) => {
    const product = products.get(row.product);
    const quantity = quantityOf(row.quantity);
    const price = centsOf(row.price);
    return {
      row,
      product,
      quantity,
      price,
      list: product?.price_usd_cents ?? null,
      amount: quantity === null || price === null ? null : quantity * price,
    };
  });
  const filled = values.filter((value) => value.row.product !== "");
  const total = filled.reduce((sum, value) => sum + (value.amount ?? 0), 0);
  const lowered = filled.some(
    (value) =>
      value.price !== null && value.list !== null && value.price < value.list,
  );

  const update = (key: string, patch: Partial<Row>) => {
    setRows((current) => {
      const next = current.map((row) =>
        row.key === key ? { ...row, ...patch } : row,
      );
      // A new empty row appears when the last one is used (mock-up round 16).
      const last = next[next.length - 1];
      if (last !== undefined && last.product !== "" && next.length < MAX_LINES)
        next.push(blankRow());
      return next;
    });
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFailure(null);
    const found: Field[] = [];
    if (chosen === undefined) found.push("cust");
    if (
      filled.length === 0 ||
      filled.some(
        (value) =>
          value.product === undefined ||
          value.quantity === null ||
          value.price === null,
      )
    )
      found.push("items");
    else if (
      filled.some(
        (value) =>
          value.price !== null &&
          value.list !== null &&
          value.price > value.list,
      )
    )
      found.push("up");
    if (lowered && lowReason.trim() === "") found.push("low");
    setProblems(found);
    if (found.length > 0 || chosen === undefined) return;
    setBusy(true);
    void api
      .make(propertyId, {
        customer_id: chosen.id,
        lease_id: chosen.lease === "" ? null : chosen.lease,
        note: note.trim() === "" ? null : note.trim(),
        replaces_id: replacing?.quotation_id ?? null,
        lowered_reason: lowered ? lowReason.trim() : null,
        lines: filled.map((value) => ({
          product_id: value.row.product,
          quantity: value.quantity ?? 0,
          price_usd_cents: value.price ?? 0,
        })),
      })
      .then((made) => {
        onSaved(made);
      })
      .catch((error: unknown) => {
        setBusy(false);
        setFailure(
          error instanceof QuotationsError
            ? error.status === 403
              ? qt(language, "f_right")
              : error.status === 409 || error.status === 422
                ? qt(language, "f_refused")
                : qt(language, "f_failed")
            : qt(language, "f_failed"),
        );
      });
  };

  const shown = new Set(problems ?? []);
  const error = (field: Field) =>
    shown.has(field) && (
      <p className="ui-error" id={`${IDS[field]}-err-${field}`}>
        <Icon name="alert" small />
        <span>{qt(language, ERRORS[field])}</span>
      </p>
    );
  const categories = catalogue.categories.filter((category) =>
    catalogue.products.some(
      (product) => product.category_code === category.code,
    ),
  );

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>
            {replacing !== null
              ? qt(language, "new_ver", replacing.quotation_number)
              : qt(language, "new_t")}
          </h2>
          <p>{qt(language, replacing !== null ? "new_ver_h" : "new_sub")}</p>
        </div>
      </div>
      <div className="ui-split ui-split-wide">
        <form
          aria-label={qt(language, "new_t")}
          className="ui-card ui-form ui-pageform"
          noValidate
          onSubmit={submit}
        >
          {problems !== null && problems.length > 0 && (
            <div
              className="ui-notice err"
              ref={summary}
              role="alert"
              tabIndex={-1}
            >
              <Icon name="alert" />
              <div>
                <b>
                  {problems.length === 1
                    ? qt(language, "e_sum1")
                    : qt(language, "e_sum", problems.length)}
                </b>
                <ul>
                  {problems.map((problem) => (
                    <li key={problem}>
                      <a href={`#${IDS[problem]}`}>
                        {qt(language, ERRORS[problem])}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {customers.length === 0 ? (
            <div className="ui-notice warn" role="status">
              <Icon name="alert" />
              <p>{qt(language, "no_customers")}</p>
            </div>
          ) : (
            <>
              <div className="ui-field">
                <label htmlFor={IDS.cust}>
                  {qt(language, "f_cust")}
                  <span className="req">{qt(language, "required")}</span>
                </label>
                <select
                  aria-describedby={
                    shown.has("cust") ? `${IDS.cust}-err-cust` : undefined
                  }
                  aria-invalid={shown.has("cust")}
                  disabled={replacing !== null}
                  id={IDS.cust}
                  onChange={(event) => {
                    setCustomer(event.currentTarget.value);
                  }}
                  value={customer}
                >
                  <option value="">{qt(language, "f_choose")}</option>
                  {customers.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.unit === ""
                        ? entry.name
                        : `${entry.name} · ${entry.unit}`}
                    </option>
                  ))}
                </select>
                {error("cust")}
              </div>
              <div className="ui-field">
                <span className="lbl" id="nq-items-lbl">
                  {qt(language, "col_prod")}
                  <span className="req">{qt(language, "required")}</span>
                </span>
                <div
                  aria-labelledby="nq-items-lbl"
                  className="ui-items"
                  id={IDS.items}
                  role="group"
                  tabIndex={-1}
                >
                  <div aria-hidden="true" className="ui-items-head">
                    <span>{qt(language, "col_prod")}</span>
                    <span>{qt(language, "col_qty")}</span>
                    <span>{qt(language, "col_price")}</span>
                    <span className="r">{qt(language, "col_amt")}</span>
                    <span />
                  </div>
                  {values.map((value, index) => {
                    const { row, product } = value;
                    const number = index + 1;
                    const last = index === rows.length - 1;
                    const low =
                      value.price !== null &&
                      value.list !== null &&
                      value.price < value.list;
                    return (
                      <div className="ui-item" key={row.key}>
                        <div className="desc">
                          <label
                            className="ui-item-lbl"
                            htmlFor={`nq-p-${row.key}`}
                          >
                            {`${qt(language, "col_prod")}, ${String(number)}`}
                          </label>
                          <select
                            id={`nq-p-${row.key}`}
                            onChange={(event) => {
                              const picked = products.get(
                                event.currentTarget.value,
                              );
                              update(row.key, {
                                product: event.currentTarget.value,
                                price:
                                  picked?.price_usd_cents == null
                                    ? ""
                                    : priceText(picked.price_usd_cents),
                              });
                            }}
                            value={row.product}
                          >
                            <option value="">{qt(language, "pick")}</option>
                            {categories.map((category) => (
                              <optgroup
                                key={category.code}
                                label={
                                  language === "km" && category.name_kh !== null
                                    ? category.name_kh
                                    : category.name_en
                                }
                              >
                                {catalogue.products
                                  .filter(
                                    (item) =>
                                      item.category_code === category.code,
                                  )
                                  .map((item) => (
                                    <option
                                      disabled={!quotable(item)}
                                      key={item.product_id}
                                      value={item.product_id}
                                    >
                                      {[
                                        language === "km" &&
                                        item.name_kh !== null
                                          ? item.name_kh
                                          : item.name_en,
                                        item.price_usd_cents === null
                                          ? qt(language, "opt_no_price")
                                          : usdFromCents(item.price_usd_cents),
                                        item.kind === "ITEM"
                                          ? qt(
                                              language,
                                              "opt_stock",
                                              item.stock,
                                            )
                                          : "",
                                      ]
                                        .filter(Boolean)
                                        .join(" · ")}
                                    </option>
                                  ))}
                              </optgroup>
                            ))}
                          </select>
                        </div>
                        <div className="qty">
                          <label
                            className="ui-item-lbl"
                            htmlFor={`nq-q-${row.key}`}
                          >
                            {`${qt(language, "col_qty")}, ${String(number)}`}
                          </label>
                          <input
                            autoComplete="off"
                            id={`nq-q-${row.key}`}
                            inputMode="numeric"
                            maxLength={3}
                            onChange={(event) => {
                              update(row.key, {
                                quantity: event.currentTarget.value,
                              });
                            }}
                            value={row.quantity}
                          />
                        </div>
                        <div className="price">
                          <label
                            className="ui-item-lbl"
                            htmlFor={`nq-c-${row.key}`}
                          >
                            {`${qt(language, "col_price")}, ${String(number)}`}
                          </label>
                          <div className="ui-money">
                            <span aria-hidden="true">$</span>
                            <input
                              autoComplete="off"
                              id={`nq-c-${row.key}`}
                              inputMode="decimal"
                              onChange={(event) => {
                                update(row.key, {
                                  price: event.currentTarget.value,
                                });
                              }}
                              readOnly={!mayLower || product === undefined}
                              value={row.price}
                            />
                          </div>
                          {low && value.list !== null && (
                            <small className="help">
                              {qt(
                                language,
                                "lowered",
                                usdFromCents(value.list),
                              )}
                            </small>
                          )}
                        </div>
                        <output
                          aria-label={`${qt(language, "col_amt")}, ${String(number)}`}
                          className="amt ui-num"
                        >
                          {value.amount === null || product === undefined
                            ? "—"
                            : usdFromCents(value.amount)}
                        </output>
                        <button
                          aria-label={`${qt(language, "remove")} ${String(number)}`}
                          className="ui-btn rm"
                          disabled={last}
                          onClick={() => {
                            setRows((current) =>
                              current.filter((item) => item.key !== row.key),
                            );
                          }}
                          type="button"
                        >
                          <Icon name="x" small />
                        </button>
                      </div>
                    );
                  })}
                  <div className="ui-items-foot">
                    <span className="help">
                      <Icon name={mayLower ? "info" : "lock"} small />{" "}
                      {qt(language, mayLower ? "price_mgr" : "price_lock")}
                    </span>
                    <span className="ui-items-total">
                      <span>{qt(language, "total")}</span>
                      <b className="ui-num" role="status">
                        {usdFromCents(total)}
                      </b>
                    </span>
                  </div>
                  {rows.length >= MAX_LINES && (
                    <p className="help">{qt(language, "e_max")}</p>
                  )}
                </div>
                {error("items")}
                {error("up")}
              </div>
              {lowered && (
                <div className="ui-field">
                  <label htmlFor={IDS.low}>
                    {qt(language, "low_reason")}
                    <span className="req">{qt(language, "required")}</span>
                  </label>
                  <input
                    aria-describedby={
                      shown.has("low") ? `${IDS.low}-err-low` : undefined
                    }
                    aria-invalid={shown.has("low")}
                    autoComplete="off"
                    id={IDS.low}
                    maxLength={500}
                    onChange={(event) => {
                      setLowReason(event.currentTarget.value);
                    }}
                    placeholder={qt(language, "low_reason_ph")}
                    value={lowReason}
                  />
                  {error("low")}
                </div>
              )}
              <div className="ui-field">
                <label htmlFor="nq-note">
                  {qt(language, "note")}
                  <span className="req">{qt(language, "optional")}</span>
                </label>
                <input
                  autoComplete="off"
                  id="nq-note"
                  maxLength={200}
                  onChange={(event) => {
                    setNote(event.currentTarget.value);
                  }}
                  placeholder={qt(language, "note_ph")}
                  value={note}
                />
              </div>
              <div className="ui-notice" role="note">
                <Icon name="clock" />
                <p>{qt(language, "valid")}</p>
              </div>
              {failure !== null && (
                <div className="ui-notice err" role="alert">
                  <Icon name="alert" />
                  <p>{failure}</p>
                </div>
              )}
              <div className="ui-actions">
                <button
                  className="ui-btn primary"
                  disabled={busy}
                  type="submit"
                >
                  <Icon name="print" />
                  {qt(language, "save")}
                </button>
                <button
                  className="ui-btn"
                  onClick={() => {
                    openPageInAddress("quotations");
                  }}
                  type="button"
                >
                  {qt(language, "cancel")}
                </button>
              </div>
            </>
          )}
        </form>
        <div className="ui-stack">
          <section aria-labelledby="nq-next" className="ui-card">
            <h2 id="nq-next">{qt(language, "w_t")}</h2>
            <ol className="ui-steps">
              <li>{qt(language, "w1")}</li>
              <li>{qt(language, "w2")}</li>
              <li>{qt(language, "w3_plain")}</li>
              <li>{qt(language, "w4")}</li>
            </ol>
            <p className="help">{qt(language, "damage_moved")}</p>
          </section>
        </div>
      </div>
    </>
  );
}
