// V1-058 R5: Create Invoice (DESIGN.md "Create Invoice and Draft Invoices"). Only one-time
// Miscellaneous charges are typed here; a Damage charge comes from a Move-out inspection finding.
// DL-103 (owner, 2026-10-28): one Invoice holds 1 to 20 items, each a whole quantity times a unit
// price, with one reason and one approval for all of them. Saving records every item's charge and
// the Draft in one request that keeps its ids and key while the form is unchanged, so "Save" again
// after an unknown result is saved once. Edit items ("#/invoices/edit:<id>") changes the items of
// such a Draft with the reason for the change; an item that stays the same keeps its charge.

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  InvoiceClientError,
  REGULAR_SERVICES_EVIDENCE,
  type InvoiceApi,
  type InvoiceResource,
  type JsonValue,
} from "../invoiceClient";
import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { RegularServicesApi } from "../settings/serviceSettingsClient";
import { type InvoicesData, centsOf } from "./invoicesData";
import { ServicesInvoice } from "./ServicesInvoice";
import { ivt, type InvoicesTextKey } from "./text";

/** At most 20 items on one Invoice, each a whole quantity from 1 to 9999 (owner, DL-103). */
export const MAX_ITEMS = 20;
const MAX_QUANTITY = 9_999;

interface Saved {
  charge: string;
  description: string;
  quantity: number;
  price: number;
}

interface Row {
  /** The row's own key on this screen. */
  key: string;
  description: string;
  quantity: string;
  price: string;
  /** Edit items: the item's charge and its saved values. */
  saved?: Saved;
}

/** What the form starts with: empty for a new Invoice, the Draft's items for Edit items. */
interface Start {
  customer: string;
  rows: Row[];
  reason: string;
  source: string;
}

type Field = "cust" | "reason" | "src" | "change";
type ItemPart = "d" | "q" | "p";
type Problem = Field | `${ItemPart}:${string}`;

const IDS: Record<Field, string> = {
  cust: "ni-cust",
  reason: "ni-reason",
  src: "ni-src",
  change: "ni-change",
};

const ERRORS: Record<Field, InvoicesTextKey> = {
  cust: "ni_err_cust",
  reason: "ni_err_reason",
  src: "ni_err_src",
  change: "ni_err_change",
};

const ITEM_ERRORS: Record<ItemPart, InvoicesTextKey> = {
  d: "ni_err_item_desc",
  q: "ni_err_item_qty",
  p: "ni_err_item_price",
};

type Outcome = "unknown" | "refused" | null;

function blankRow(): Row {
  return {
    key: crypto.randomUUID(),
    description: "",
    quantity: "1",
    price: "",
  };
}

function quantityOf(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,4}$/.test(value)) return null;
  const number = Number(value);
  return number >= 1 && number <= MAX_QUANTITY ? number : null;
}

function wholeOf(value: JsonValue | undefined): number | null {
  if (typeof value === "bigint")
    return value <= BigInt(Number.MAX_SAFE_INTEGER) && value > 0n
      ? Number(value)
      : null;
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : null;
}

function textOf(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/** "15.00" for 1500 cents, the way the price box reads it. */
function priceText(value: number): string {
  return `${String(Math.floor(value / 100))}.${String(value % 100).padStart(2, "0")}`;
}

/**
 * The items of a Draft that Edit items can change, or null when it cannot: only a Miscellaneous
 * Draft whose every line bills a typed item (a quantity and a unit price) can be edited.
 */
export function editableItems(invoice: InvoiceResource): Start | null {
  if (
    invoice.status !== "DRAFT" ||
    invoice.category !== "MISCELLANEOUS_CHARGES" ||
    invoice.lines.length === 0
  )
    return null;
  const lines = [...invoice.lines].sort(
    (left, right) => left.sequence - right.sequence,
  );
  // DL-115 (I): a Services Invoice takes its prices from Settings, so its items are never typed.
  if (
    lines.some(
      (line) =>
        line.calculation_evidence.evidence_reference ===
        REGULAR_SERVICES_EVIDENCE,
    )
  )
    return null;
  const rows: Row[] = [];
  for (const line of lines) {
    const quantity = wholeOf(line.calculation_evidence.quantity);
    const price = wholeOf(line.calculation_evidence.unit_price_usd_cents);
    const charge = textOf(line.source.id);
    if (quantity === null || price === null || charge === null) return null;
    rows.push({
      key: charge,
      description: line.description,
      quantity: String(quantity),
      price: priceText(price),
      saved: { charge, description: line.description, quantity, price },
    });
  }
  const evidence = lines[0]?.calculation_evidence ?? {};
  return {
    customer: invoice.customer_id,
    rows,
    reason: textOf(evidence.reason) ?? "",
    source: textOf(evidence.evidence_reference) ?? "",
  };
}

type Api = Pick<
  InvoiceApi,
  "createWithItems" | "createWithServices" | "replaceItems" | "get"
>;

export function CreateInvoice({
  language,
  propertyId,
  api,
  data,
  onSaved,
  editId,
  servicesApi,
}: {
  language: Language;
  propertyId: string;
  api: Api;
  data: InvoicesData;
  /** The list reads again, so it shows the new or changed Draft. */
  onSaved: () => void;
  /** Edit items of this Draft instead of making a new Invoice. */
  editId?: string;
  /** V1.1: the Regular services the Services kind picks from. */
  servicesApi?: Pick<RegularServicesApi, "read">;
}) {
  if (editId === undefined)
    return (
      <ItemsForm
        api={api}
        data={data}
        language={language}
        onSaved={onSaved}
        propertyId={propertyId}
        servicesApi={servicesApi}
        start={{ customer: "", rows: [blankRow()], reason: "", source: "" }}
      />
    );
  return (
    <EditItems
      api={api}
      data={data}
      editId={editId}
      language={language}
      onSaved={onSaved}
      propertyId={propertyId}
    />
  );
}

/** Edit items reads the Draft again, so it starts from the items as they are now. */
function EditItems({
  language,
  propertyId,
  api,
  data,
  onSaved,
  editId,
}: {
  language: Language;
  propertyId: string;
  api: Api;
  data: InvoicesData;
  onSaved: () => void;
  editId: string;
}) {
  const [invoice, setInvoice] = useState<InvoiceResource | null>(null);
  const [failed, setFailed] = useState(false);
  const [changed, setChanged] = useState(false);
  const sequence = useRef(0);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setFailed(false);
    void api
      .get(editId)
      .then((found) => {
        if (operation === sequence.current) setInvoice(found);
      })
      .catch(() => {
        if (operation === sequence.current) setFailed(true);
      });
  }, [api, editId]);

  useEffect(() => {
    load();
  }, [load]);

  const toInvoice = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("invoices", false, `inv:${editId}`);
      }}
      type="button"
    >
      <Icon name="back" small />
      {ivt(language, "ni_back_one")}
    </button>
  );
  if (failed)
    return (
      <>
        {toInvoice}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ivt(language, "failed")}</p>
          <button className="ui-btn" onClick={load} type="button">
            {ivt(language, "retry")}
          </button>
        </div>
      </>
    );
  if (invoice === null)
    return (
      <p className="ui-muted" role="status">
        {ivt(language, "loading_one")}
      </p>
    );
  const start =
    invoice.property_id === propertyId ? editableItems(invoice) : null;
  if (start === null)
    return (
      <>
        {toInvoice}
        <div className="ui-notice" role="note">
          <Icon name="info" />
          <p>{ivt(language, "ni_not_editable")}</p>
        </div>
      </>
    );
  return (
    <ItemsForm
      api={api}
      changed={changed}
      data={data}
      invoice={invoice}
      // A Draft read again after a change meanwhile starts the form again.
      key={invoice.version}
      language={language}
      onChangedMeanwhile={() => {
        setChanged(true);
        load();
      }}
      onSaved={onSaved}
      propertyId={propertyId}
      start={start}
    />
  );
}

function ItemsForm({
  language,
  propertyId,
  api,
  data,
  onSaved,
  start,
  invoice,
  changed = false,
  onChangedMeanwhile,
  servicesApi,
}: {
  language: Language;
  propertyId: string;
  api: Api;
  data: InvoicesData;
  onSaved: () => void;
  start: Start;
  servicesApi?: Pick<RegularServicesApi, "read">;
  /** Edit items: the Draft as it was read. */
  invoice?: InvoiceResource;
  /** Edit items: the Draft changed meanwhile and was read again. */
  changed?: boolean;
  onChangedMeanwhile?: () => void;
}) {
  const editing = invoice !== undefined;
  const [kind, setKind] = useState<"MISC" | "SERVICES" | "DAMAGE">("MISC");
  const [customer, setCustomer] = useState(start.customer);
  const [rows, setRows] = useState<Row[]>(start.rows);
  const [reason, setReason] = useState(start.reason);
  const [source, setSource] = useState(start.source);
  const [change, setChange] = useState("");
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [done, setDone] = useState<InvoiceResource | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const focusNext = useRef<string | null>(null);
  // One key and one charge per item for these exact values; a change makes a new request.
  const identity = useRef<{
    sent: string;
    key: string;
    charges: Map<string, string>;
  } | null>(null);

  useEffect(() => {
    if (focusNext.current === null) return;
    document.getElementById(focusNext.current)?.focus();
    focusNext.current = null;
  });

  const listed = [...data.customerLeases.keys()];
  // Edit items keeps the Draft's Customer on the list even without a signed Lease now.
  if (editing && !data.customerLeases.has(invoice.customer_id))
    listed.push(invoice.customer_id);
  const customers = listed
    .map((id) => ({
      id,
      name: data.names.get(id) ?? ivt(language, "unknown_customer"),
      unit: data.customerUnits.get(id) ?? "",
    }))
    .sort(
      (left, right) =>
        left.unit.localeCompare(right.unit, undefined, { numeric: true }) ||
        left.name.localeCompare(right.name),
    );
  const chosen = customers.find((entry) => entry.id === customer);
  // The Draft keeps its Lease while its Customer stays; another Customer's newest Lease otherwise.
  const leaseId =
    editing && customer === invoice.customer_id
      ? invoice.lease_id
      : (data.customerLeases.get(customer) ?? null);
  const values = rows.map((row) => {
    const quantity = quantityOf(row.quantity);
    const price = centsOf(row.price);
    return {
      row,
      description: row.description.trim(),
      quantity,
      price,
      amount: quantity === null || price === null ? null : quantity * price,
    };
  });
  const total = values.reduce((sum, value) => sum + (value.amount ?? 0), 0);
  const label = (entry: { name: string; unit: string }) =>
    entry.unit === "" ? entry.name : `${entry.name} · ${entry.unit}`;

  const check = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found: Problem[] = [];
    if (chosen === undefined) found.push("cust");
    for (const value of values) {
      if (value.description === "") found.push(`d:${value.row.key}`);
      if (value.quantity === null) found.push(`q:${value.row.key}`);
      if (value.price === null) found.push(`p:${value.row.key}`);
    }
    if (reason.trim() === "") found.push("reason");
    if (source.trim() === "") found.push("src");
    if (editing && change.trim() === "") found.push("change");
    setProblems(found);
    if (found.length > 0) {
      // The summary takes the focus, so a screen reader reads what to fix.
      setTimeout(() => summary.current?.focus(), 0);
      return;
    }
    setOutcome(null);
    setConfirming(true);
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (chosen === undefined || busy) return;
    const items = values.flatMap((value) =>
      value.quantity === null || value.price === null
        ? []
        : [{ ...value, quantity: value.quantity, price: value.price }],
    );
    if (items.length !== values.length) return;
    const sent = JSON.stringify({
      customer: chosen.id,
      leaseId,
      reason: reason.trim(),
      source: source.trim(),
      change: change.trim(),
      items: items.map((item) => [
        item.row.key,
        item.description,
        item.quantity,
        item.price,
      ]),
    });
    if (identity.current?.sent !== sent) {
      // An item keeps its charge only while it, the Customer, the Lease, the reason and what
      // approves it all stay the same; anything else is a new charge (the server checks this).
      const sameSource =
        editing &&
        chosen.id === invoice.customer_id &&
        leaseId === invoice.lease_id &&
        reason.trim() === start.reason &&
        source.trim() === start.source;
      identity.current = {
        sent,
        key: crypto.randomUUID(),
        charges: new Map(
          items.map((item) => {
            const saved = item.row.saved;
            const kept =
              sameSource &&
              saved !== undefined &&
              saved.description === item.description &&
              saved.quantity === item.quantity &&
              saved.price === item.price;
            return [
              item.row.key,
              kept ? saved.charge : crypto.randomUUID(),
            ] as const;
          }),
        ),
      };
    }
    const { key, charges } = identity.current;
    const input = {
      customer_id: chosen.id,
      lease_id: leaseId,
      reason: reason.trim(),
      evidence_reference: source.trim(),
      items: items.map((item) => ({
        charge_id: charges.get(item.row.key) ?? crypto.randomUUID(),
        description: item.description,
        quantity: item.quantity,
        unit_price: { currency: "USD" as const, minor_units: item.price },
      })),
    };
    setBusy(true);
    setOutcome(null);
    const request = editing
      ? api.replaceItems(
          invoice.id,
          { ...input, change_reason: change.trim() },
          invoice.version,
          key,
        )
      : api.createWithItems(propertyId, input, key);
    void request
      .then((draft) => {
        setDone(draft);
        setConfirming(false);
        onSaved();
      })
      .catch((error: unknown) => {
        if (
          editing &&
          error instanceof InvoiceClientError &&
          error.status === 412 &&
          onChangedMeanwhile !== undefined
        ) {
          setConfirming(false);
          onChangedMeanwhile();
          return;
        }
        setOutcome(
          error instanceof InvoiceClientError && !error.outcomeUnknown
            ? "refused"
            : "unknown",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const backToList = () => {
    openPageInAddress("invoices");
  };
  const back = editing ? (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("invoices", false, `inv:${invoice.id}`);
      }}
      type="button"
    >
      <Icon name="back" small />
      {ivt(language, "ni_back_one")}
    </button>
  ) : (
    <button className="ui-crumb" onClick={backToList} type="button">
      <Icon name="back" small />
      {ivt(language, "back")}
    </button>
  );

  const kindPicker = (
    <div className="ui-field">
      <span className="lbl" id="ni-kind">
        {ivt(language, "ni_kind")}
      </span>
      <div aria-labelledby="ni-kind" className="ui-seg" role="group">
        {(
          [
            ["MISC", "MISCELLANEOUS_CHARGES"],
            ...(servicesApi === undefined
              ? []
              : ([["SERVICES", "SERVICES"]] as const)),
            ["DAMAGE", "DAMAGE_CHARGES"],
          ] as const
        ).map(([value, key]) => (
          <button
            aria-pressed={kind === value}
            key={value}
            onClick={() => {
              setKind(value);
            }}
            type="button"
          >
            {ivt(language, key)}
          </button>
        ))}
      </div>
    </div>
  );
  if (kind === "SERVICES" && !editing && servicesApi !== undefined) {
    return (
      <ServicesInvoice
        api={api}
        back={back}
        customers={customers}
        kindPicker={kindPicker}
        language={language}
        leaseOf={(id) => data.customerLeases.get(id) ?? null}
        onSaved={onSaved}
        propertyId={propertyId}
        servicesApi={servicesApi}
      />
    );
  }

  if (done !== null) {
    return (
      <>
        <div className="ui-head">
          <div className="ui-hrow">
            <h2>{ivt(language, editing ? "ni_edit_done_t" : "ni_done_t")}</h2>
            <Chip tone="info">{ivt(language, "st_draft")}</Chip>
          </div>
        </div>
        <section className="ui-card">
          <div className="ui-notice ok" role="status">
            <Icon name="check" />
            <p>
              {ivt(
                language,
                editing ? "ni_edit_done_b" : "ni_done_b",
                chosen?.name ?? "",
                chosen?.unit ?? "",
                values.length,
                usdFromCents(total),
              )}
            </p>
          </div>
          <div className="ui-actions">
            <a
              className="ui-btn primary"
              href={hashForPage("invoices", `inv:${done.id}`)}
            >
              <Icon name="invoice" />
              {ivt(language, "ni_open")}
            </a>
            <button className="ui-btn" onClick={backToList} type="button">
              {ivt(language, "ni_to_list")}
            </button>
          </div>
        </section>
      </>
    );
  }

  const shown = new Set<Problem>(problems ?? []);
  const itemNumber = (key: string) =>
    rows.findIndex((row) => row.key === key) + 1;
  const problemId = (problem: Problem) => {
    if (!problem.includes(":")) return IDS[problem as Field];
    const [part, key] = problem.split(":") as [ItemPart, string];
    return `ni-${part}-${key}`;
  };
  const problemText = (problem: Problem) => {
    if (!problem.includes(":")) return ivt(language, ERRORS[problem as Field]);
    const [part, key] = problem.split(":") as [ItemPart, string];
    return ivt(language, ITEM_ERRORS[part], itemNumber(key));
  };
  const field = (
    name: Field,
    labelKey: InvoicesTextKey,
    input: ReactNode,
    help?: InvoicesTextKey,
  ) => (
    <div className="ui-field">
      <label htmlFor={IDS[name]}>
        {ivt(language, labelKey)}
        <span className="req">{ivt(language, "required")}</span>
      </label>
      {input}
      {help !== undefined && (
        <p className="help" id={`${IDS[name]}-help`}>
          {ivt(language, help)}
        </p>
      )}
      {shown.has(name) && (
        <p className="ui-error" id={`${IDS[name]}-err`}>
          <Icon name="alert" small />
          <span>{ivt(language, ERRORS[name])}</span>
        </p>
      )}
    </div>
  );
  const describedBy = (name: Field, help: boolean) =>
    [help ? `${IDS[name]}-help` : "", shown.has(name) ? `${IDS[name]}-err` : ""]
      .filter(Boolean)
      .join(" ") || undefined;
  const update = (key: string, patch: Partial<Row>) => {
    setRows((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  };

  const itemsTable = (
    <div className="ui-field">
      <span className="lbl" id="ni-items">
        {ivt(language, "ni_items")}
        <span className="req">{ivt(language, "required")}</span>
      </span>
      <p className="help" id="ni-items-help">
        {ivt(language, "ni_items_help")}
      </p>
      <div
        aria-describedby="ni-items-help"
        aria-labelledby="ni-items"
        className="ui-items"
        role="group"
      >
        <div aria-hidden="true" className="ui-items-head">
          <span>{ivt(language, "ni_desc")}</span>
          <span>{ivt(language, "ni_qty")}</span>
          <span>{ivt(language, "ni_price")}</span>
          <span className="r">{ivt(language, "ni_line_amt")}</span>
          <span />
        </div>
        {values.map((value, index) => {
          const { row } = value;
          const number = index + 1;
          const bad = (part: ItemPart) => shown.has(`${part}:${row.key}`);
          const errors = (["d", "q", "p"] as const).filter(bad);
          const errorId = `ni-row-${row.key}-err`;
          return (
            <div className="ui-item" key={row.key}>
              <div className="desc">
                <label className="ui-item-lbl" htmlFor={`ni-d-${row.key}`}>
                  {`${ivt(language, "ni_desc")}, ${ivt(language, "ni_item_n", number)}`}
                </label>
                <input
                  aria-describedby={bad("d") ? errorId : undefined}
                  aria-invalid={bad("d")}
                  autoComplete="off"
                  id={`ni-d-${row.key}`}
                  maxLength={80}
                  onChange={(event) => {
                    update(row.key, { description: event.currentTarget.value });
                  }}
                  value={row.description}
                />
              </div>
              <div className="qty">
                <label className="ui-item-lbl" htmlFor={`ni-q-${row.key}`}>
                  {`${ivt(language, "ni_qty")}, ${ivt(language, "ni_item_n", number)}`}
                </label>
                <input
                  aria-describedby={bad("q") ? errorId : undefined}
                  aria-invalid={bad("q")}
                  autoComplete="off"
                  id={`ni-q-${row.key}`}
                  inputMode="numeric"
                  maxLength={4}
                  onChange={(event) => {
                    update(row.key, { quantity: event.currentTarget.value });
                  }}
                  value={row.quantity}
                />
              </div>
              <div className="price">
                <label className="ui-item-lbl" htmlFor={`ni-p-${row.key}`}>
                  {`${ivt(language, "ni_price")}, ${ivt(language, "ni_item_n", number)}`}
                </label>
                <div className="ui-money">
                  <span aria-hidden="true">$</span>
                  <input
                    aria-describedby={bad("p") ? errorId : undefined}
                    aria-invalid={bad("p")}
                    autoComplete="off"
                    id={`ni-p-${row.key}`}
                    inputMode="decimal"
                    onChange={(event) => {
                      update(row.key, { price: event.currentTarget.value });
                    }}
                    value={row.price}
                  />
                </div>
              </div>
              <output
                aria-label={`${ivt(language, "ni_line_amt")}, ${ivt(language, "ni_item_n", number)}`}
                className="amt ui-num"
              >
                {value.amount === null ? "—" : usdFromCents(value.amount)}
              </output>
              <button
                aria-label={ivt(language, "ni_remove", number)}
                className="ui-btn rm"
                disabled={rows.length === 1}
                onClick={() => {
                  const next = rows[index + 1] ?? rows[index - 1];
                  focusNext.current =
                    next === undefined ? null : `ni-d-${next.key}`;
                  setRows((current) =>
                    current.filter((item) => item.key !== row.key),
                  );
                }}
                type="button"
              >
                <Icon name="x" small />
              </button>
              {errors.length > 0 && (
                <div className="ui-item-errs" id={errorId}>
                  {errors.map((part) => (
                    <p className="ui-error" key={part}>
                      <Icon name="alert" small />
                      <span>{ivt(language, ITEM_ERRORS[part], number)}</span>
                    </p>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        <div className="ui-items-foot">
          <button
            className="ui-btn"
            disabled={rows.length >= MAX_ITEMS}
            onClick={() => {
              const row = blankRow();
              focusNext.current = `ni-d-${row.key}`;
              setRows((current) => [...current, row]);
            }}
            type="button"
          >
            <Icon name="plus" small />
            {ivt(language, "ni_add")}
          </button>
          <span className="ui-items-total">
            <span>{ivt(language, "ni_total")}</span>
            <b className="ui-num" role="status">
              {usdFromCents(total)}
            </b>
          </span>
        </div>
        {rows.length >= MAX_ITEMS && (
          <p className="help">{ivt(language, "ni_items_max")}</p>
        )}
      </div>
    </div>
  );

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <h2>{ivt(language, editing ? "ni_edit_t" : "ni_btn")}</h2>
          <p>{ivt(language, editing ? "ni_edit_intro" : "ni_intro")}</p>
        </div>
      </div>
      {changed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ivt(language, "changed")}</p>
        </div>
      )}
      <div className="ui-split ui-split-wide">
        <form
          aria-label={ivt(language, editing ? "ni_edit_t" : "ni_btn")}
          className="ui-card ui-form ui-pageform"
          noValidate
          onSubmit={check}
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
                <b>{ivt(language, "err_sum", problems.length)}</b>
                <ul>
                  {problems.map((problem) => (
                    <li key={problem}>
                      <a
                        href={`#${problemId(problem)}`}
                        onClick={(event) => {
                          event.preventDefault();
                          document.getElementById(problemId(problem))?.focus();
                        }}
                      >
                        {problemText(problem)}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {!editing && kindPicker}
          {kind === "DAMAGE" ? (
            <div className="ui-notice" role="note">
              <Icon name="info" />
              <p>{ivt(language, "ni_damage")}</p>
            </div>
          ) : customers.length === 0 ? (
            <div className="ui-notice warn" role="status">
              <Icon name="alert" />
              <p>{ivt(language, "ni_none")}</p>
            </div>
          ) : (
            <>
              {field(
                "cust",
                "f_customer",
                <select
                  aria-describedby={describedBy("cust", true)}
                  aria-invalid={shown.has("cust")}
                  id={IDS.cust}
                  onChange={(event) => {
                    setCustomer(event.currentTarget.value);
                  }}
                  value={customer}
                >
                  <option value="">{ivt(language, "f_choose")}</option>
                  {customers.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {label(entry)}
                    </option>
                  ))}
                </select>,
                "ni_cust_help",
              )}
              {itemsTable}
              {field(
                "reason",
                "ni_reason",
                <input
                  aria-describedby={describedBy("reason", true)}
                  aria-invalid={shown.has("reason")}
                  autoComplete="off"
                  id={IDS.reason}
                  maxLength={500}
                  onChange={(event) => {
                    setReason(event.currentTarget.value);
                  }}
                  value={reason}
                />,
                "ni_one_reason",
              )}
              {field(
                "src",
                "ni_src",
                <input
                  aria-describedby={describedBy("src", true)}
                  aria-invalid={shown.has("src")}
                  autoComplete="off"
                  id={IDS.src}
                  maxLength={500}
                  onChange={(event) => {
                    setSource(event.currentTarget.value);
                  }}
                  value={source}
                />,
                "ni_src_help",
              )}
              {editing &&
                field(
                  "change",
                  "ni_change",
                  <input
                    aria-describedby={describedBy("change", true)}
                    aria-invalid={shown.has("change")}
                    autoComplete="off"
                    id={IDS.change}
                    maxLength={500}
                    onChange={(event) => {
                      setChange(event.currentTarget.value);
                    }}
                    value={change}
                  />,
                  "ni_change_help",
                )}
              <div className="ui-actions">
                <button className="ui-btn primary" type="submit">
                  <Icon name="check" />
                  {ivt(language, editing ? "ni_edit_submit" : "ni_submit")}
                </button>
                <button
                  className="ui-btn"
                  onClick={() => {
                    if (editing)
                      openPageInAddress("invoices", false, `inv:${invoice.id}`);
                    else backToList();
                  }}
                  type="button"
                >
                  {ivt(language, "cancel")}
                </button>
              </div>
            </>
          )}
        </form>
        <div className="ui-stack">
          <section aria-labelledby="ni-next" className="ui-card">
            <h2 id="ni-next">{ivt(language, "ni_what_t")}</h2>
            <ol className="ui-steps">
              <li>{ivt(language, "ni_w1")}</li>
              <li>{ivt(language, "ni_w2")}</li>
              <li>{ivt(language, "ni_w3")}</li>
              <li>{ivt(language, "ni_w4")}</li>
            </ol>
          </section>
        </div>
      </div>
      {confirming && chosen !== undefined && (
        <Dialog
          busy={busy}
          closeLabel={ivt(language, "cancel")}
          onClose={() => {
            setConfirming(false);
          }}
          onSubmit={save}
          submitLabel={ivt(language, editing ? "ni_edit_submit" : "ni_submit")}
          title={ivt(language, editing ? "ni_edit_dlg_t" : "ni_dlg_t")}
          wide
        >
          <dl className="ui-kv">
            <dt>{ivt(language, "ni_kind")}</dt>
            <dd>{ivt(language, "MISCELLANEOUS_CHARGES")}</dd>
            <dt>{ivt(language, "f_customer")}</dt>
            <dd>{label(chosen)}</dd>
          </dl>
          <div className="ui-tablewrap">
            <table className="ui-table fit">
              <caption className="ui-sr">{ivt(language, "ni_items")}</caption>
              <thead>
                <tr>
                  <th scope="col">{ivt(language, "ni_desc")}</th>
                  <th className="r" scope="col">
                    {ivt(language, "ni_qty")}
                  </th>
                  <th className="r" scope="col">
                    {ivt(language, "ni_price")}
                  </th>
                  <th className="r" scope="col">
                    {ivt(language, "ni_line_amt")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {values.map((value) => (
                  <tr key={value.row.key}>
                    <td className="wrap">{value.description}</td>
                    <td className="r ui-num">{value.quantity}</td>
                    <td className="r ui-num">
                      {usdFromCents(value.price ?? 0)}
                    </td>
                    <td className="r ui-num">
                      {usdFromCents(value.amount ?? 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={3} scope="row">
                    {ivt(language, "ni_total")}
                  </th>
                  <td className="r ui-num">
                    <b>{usdFromCents(total)}</b>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          <dl className="ui-kv">
            <dt>{ivt(language, "ni_reason")}</dt>
            <dd>{reason.trim()}</dd>
            <dt>{ivt(language, "ni_src")}</dt>
            <dd>{source.trim()}</dd>
            {editing && (
              <>
                <dt>{ivt(language, "ni_change")}</dt>
                <dd>{change.trim()}</dd>
              </>
            )}
          </dl>
          <p>{ivt(language, editing ? "ni_edit_dlg_c" : "ni_dlg_c")}</p>
          {outcome !== null && (
            <div className="ui-notice warn" role="alert">
              <Icon name="alert" />
              <p>{ivt(language, outcome)}</p>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
