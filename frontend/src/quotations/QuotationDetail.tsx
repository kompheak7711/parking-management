// V1.1 part 6 (DL-123): one Quotation (mock-up round 16 "one Quotation"): the head with its
// number, status and buttons, the status path Quotation → Customer signs → Invoice issued →
// Paid, the notice of its state, the printed Quotation, where each Item was taken from, the
// Customer and the History. Customer signed asks for the day and, for each Item, the place it
// is taken from; the server issues the Invoice and takes the Items out of stock, or refuses
// while an Item is not in stock there.

import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { BackLink } from "../shell/backNav";

import { SheetFrame } from "../invoices/InvoiceDocument";
import {
  type Locations,
  type Place,
  type ProductsApi,
} from "../products/productsClient";
import { placeLabel } from "../products/StockDialogs";
import { DateInput, isDay } from "../shell/DateInput";
import {
  dayText,
  momentText,
  todayInPhnomPenh,
  usdFromCents,
} from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { QuotationDocument } from "./QuotationDocument";
import {
  type Quotation,
  QuotationsError,
  type QuotationsApi,
  type Take,
} from "./quotationsClient";
import { QuotationChip } from "./QuotationsPage";
import { qt } from "./text";
import { PageHeader } from "../shell/layouts";

/** Prints only the Quotation sheet (invoiceDocument.css), then the page is as before. */
function printSheet() {
  document.body.classList.add("ui-printing");
  const done = () => {
    document.body.classList.remove("ui-printing");
  };
  window.addEventListener("afterprint", done, { once: true });
  window.print();
}

function refusal(language: Language, error: unknown): string {
  if (error instanceof QuotationsError) {
    if (error.status === 403) return qt(language, "f_right");
    if (error.status === 412) return qt(language, "f_stale");
    if (error.status === 409 || error.status === 422)
      return qt(language, "f_refused");
  }
  return qt(language, "f_failed");
}

/** How many of a product a place holds, from the Locations read. */
function heldAt(place: Place, productId: string): number {
  const line = place.stock.find((held) => held.product_id === productId);
  return line === undefined ? 0 : Number(line.quantity);
}

function placeKey(place: { unit_id: string; item_id: string; number: number }) {
  return `${place.unit_id}|${place.item_id}|${String(place.number)}`;
}

type Problem = "failed" | "missing";

export function QuotationDetail({
  language,
  propertyId,
  quotationId,
  api,
  productsApi,
  may,
  flash,
  onFlashShown,
  today: fixedToday,
}: {
  language: Language;
  propertyId: string;
  quotationId: string;
  api: QuotationsApi;
  productsApi: Pick<ProductsApi, "locations">;
  may: (capability: string) => boolean;
  /** A message from the page before, such as "Quotation QT260001 saved". */
  flash: string | null;
  onFlashShown: () => void;
  today?: string;
}) {
  const today = fixedToday ?? todayInPhnomPenh();
  const [quotation, setQuotation] = useState<Quotation | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [notice, setNotice] = useState<string | null>(flash);
  const [dialog, setDialog] = useState<"sign" | "refuse" | null>(null);
  const sequence = useRef(0);

  useEffect(() => {
    if (flash !== null) onFlashShown();
  }, [flash, onFlashShown]);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    setProblem(null);
    void api
      .get(propertyId, quotationId)
      .then((found) => {
        if (operation === sequence.current) setQuotation(found);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(
          error instanceof QuotationsError && error.status === 404
            ? "missing"
            : "failed",
        );
      });
  }, [api, propertyId, quotationId]);

  useEffect(() => {
    load();
  }, [load]);

  const back = <BackLink language={language} parent="quotations" />;

  if (quotation === null) {
    return (
      <>
        {back}
        {problem === null ? (
          <p className="ui-muted" role="status">
            {qt(language, "loading")}
          </p>
        ) : (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>
              {qt(language, problem === "missing" ? "not_found" : "failed")}
            </p>
            {problem === "failed" && (
              <button className="ui-btn" onClick={load} type="button">
                {qt(language, "retry")}
              </button>
            )}
          </div>
        )}
      </>
    );
  }

  const state = quotation.state;
  const make = may("quotations.make");
  const paid = quotation.invoice_status === "PAID";
  const voided = quotation.invoice_status === "VOID";
  const steps = ["p_Q", "p_S", "p_I", "p_P"] as const;
  const reached = state === "SIGNED" ? (paid ? 3 : 2) : 0;
  const history: [string, string][] = [
    [
      quotation.created_at,
      [
        quotation.created_by_name === null
          ? qt(language, "h_made_plain")
          : qt(language, "h_made", quotation.created_by_name),
        quotation.replaces_number === null
          ? ""
          : qt(language, "replaces", quotation.replaces_number),
        quotation.lowered_reason === null
          ? ""
          : qt(language, "h_lowered", quotation.lowered_reason),
      ]
        .filter(Boolean)
        .join(" · "),
    ],
  ];
  if (quotation.signed_at !== null && quotation.invoice_number !== null)
    history.push([
      quotation.signed_at,
      qt(language, "h_signed", quotation.invoice_number),
    ]);
  if (state === "REPLACED" && quotation.replaced_by_number !== null)
    history.push([
      quotation.closed_at ?? "",
      qt(language, "h_replaced", quotation.replaced_by_number),
    ]);
  if (state === "REFUSED")
    history.push([
      quotation.closed_at ?? "",
      qt(language, "h_refused", quotation.refused_reason ?? ""),
    ]);

  const stateNotice =
    state === "SIGNED" ? (
      <div className={voided ? "ui-notice" : "ui-notice ok"} role="note">
        <Icon name={voided ? "info" : "check"} />
        <p>
          {voided
            ? qt(language, "voided_n", quotation.invoice_number ?? "")
            : qt(
                language,
                "signed_n",
                dayText(quotation.signed_on),
                quotation.invoice_number ?? "",
              )}
        </p>
      </div>
    ) : state === "EXPIRED" ? (
      <div className="ui-notice err" role="note">
        <Icon name="alert" />
        <p>{qt(language, "expired_n", dayText(quotation.valid_until))}</p>
      </div>
    ) : state === "REFUSED" ? (
      <div className="ui-notice" role="note">
        <Icon name="x" />
        <p>{qt(language, "refused_n", quotation.refused_reason ?? "")}</p>
      </div>
    ) : state === "REPLACED" ? (
      <div className="ui-notice" role="note">
        <Icon name="info" />
        <p>{qt(language, "replaced_by", quotation.replaced_by_number ?? "")}</p>
      </div>
    ) : (
      <div className="ui-notice warn" role="note">
        <Icon name="clock" />
        <p>
          {qt(language, "valid_until", dayText(quotation.valid_until))} ·{" "}
          {qt(language, "w3", quotation.due_days)}
        </p>
      </div>
    );

  return (
    <>
      <PageHeader
        actions={
          <>
            {state === "WAITING" && make && (
              <button
                className="ui-btn primary"
                onClick={() => {
                  setNotice(null);
                  setDialog("sign");
                }}
                type="button"
              >
                <Icon name="check" />
                {qt(language, "sign")}
              </button>
            )}
            {state === "SIGNED" && quotation.invoice_id !== null && (
              <a
                className="ui-btn primary"
                href={hashForPage("invoices", `inv:${quotation.invoice_id}`)}
              >
                <Icon name="invoice" />
                {qt(language, "open_inv", quotation.invoice_number ?? "")}
              </a>
            )}
            {state === "REPLACED" && quotation.replaced_by_id !== null && (
              <a
                className="ui-btn primary"
                href={hashForPage(
                  "quotations",
                  `qt:${quotation.replaced_by_id}`,
                )}
              >
                <Icon name="list" />
                {qt(language, "open_next", quotation.replaced_by_number ?? "")}
              </a>
            )}
            {(state === "WAITING" || state === "SIGNED") && (
              <button className="ui-btn" onClick={printSheet} type="button">
                <Icon name="print" />
                {qt(language, "print")}
              </button>
            )}
            {state === "WAITING" && make && may("quotations.lower_price") && (
              <a
                className="ui-btn"
                href={hashForPage(
                  "quotations",
                  `new:${quotation.quotation_id}`,
                )}
              >
                <Icon name="swap" />
                {qt(language, "lower")}
              </a>
            )}
            {state === "WAITING" && make && (
              <button
                className="ui-btn"
                onClick={() => {
                  setNotice(null);
                  setDialog("refuse");
                }}
                type="button"
              >
                <Icon name="x" />
                {qt(language, "refuse")}
              </button>
            )}
            {(state === "EXPIRED" || state === "REFUSED") && make && (
              <a
                className="ui-btn primary"
                href={hashForPage(
                  "quotations",
                  `new:${quotation.quotation_id}`,
                )}
              >
                <Icon name="plus" />
                {qt(language, "again")}
              </a>
            )}
          </>
        }
        back={back}
        badge={<QuotationChip language={language} state={state} />}
        numeric
        summary={[
          qt(language, "p_Q"),
          quotation.customer_name,
          quotation.unit_number,
        ]
          .filter((part) => part !== null && part !== "")
          .join(" · ")}
        title={quotation.quotation_number}
      />
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      <section aria-labelledby="qt-status" className="ui-card">
        <h2 className="ui-sr" id="qt-status">
          {qt(language, "status")}
        </h2>
        <ol className="ui-qpath">
          {steps.map((key, index) => (
            <li
              aria-current={index === reached ? "step" : undefined}
              className={
                index < reached ? "done" : index === reached ? "cur" : undefined
              }
              key={key}
            >
              {index < reached && <Icon name="check" small />}
              {qt(language, key)}
            </li>
          ))}
        </ol>
      </section>
      {stateNotice}
      <div className="ui-split">
        <div className="ui-stack">
          <SheetFrame>
            <QuotationDocument quotation={quotation} />
          </SheetFrame>
        </div>
        <div className="ui-stack">
          {state === "SIGNED" && (
            <section aria-labelledby="qt-lines" className="ui-card">
              <h2 id="qt-lines">{qt(language, "lines_t")}</h2>
              <ul className="ui-plain ui-qlines">
                {quotation.lines.map((line) => (
                  <li key={line.position}>
                    <b>
                      {line.name_en} × {line.quantity}
                    </b>
                    <span className="ui-sub2">
                      {line.taken_from === null
                        ? qt(language, "service_line")
                        : qt(
                            language,
                            "taken",
                            `${line.taken_from.unit_number} · ${
                              language === "km" &&
                              line.taken_from.name_kh !== null
                                ? line.taken_from.name_kh
                                : line.taken_from.name_en
                            } ${String(line.taken_from.number)}`,
                            line.taken_from.movement_number,
                          )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section aria-labelledby="qt-cust" className="ui-card">
            <h2 id="qt-cust">{qt(language, "cust_t")}</h2>
            <p>
              <b>{quotation.customer_name}</b>
              {quotation.unit_number !== null && (
                <span className="ui-sub2">{quotation.unit_number}</span>
              )}
            </p>
            {may("customers.read") && (
              <div className="ui-actions">
                <a
                  className="ui-btn"
                  href={hashForPage("customers", quotation.customer_id)}
                >
                  {qt(language, "open_customer")}
                </a>
              </div>
            )}
          </section>
          <section aria-labelledby="qt-hist" className="ui-card">
            <h2 id="qt-hist">{qt(language, "history_t")}</h2>
            <ol className="ui-timeline">
              {history.map(([when, what], index) => (
                <li key={index}>
                  <div>
                    {what}
                    {when !== "" && (
                      <small className="ui-num">{momentText(when)}</small>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
      {dialog === "sign" && (
        <SignDialog
          api={api}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onSigned={(signed) => {
            setDialog(null);
            setQuotation(signed);
            setNotice(
              qt(language, "signed_toast", signed.invoice_number ?? ""),
            );
          }}
          onStale={() => {
            setDialog(null);
            setNotice(null);
            load();
          }}
          productsApi={productsApi}
          propertyId={propertyId}
          quotation={quotation}
          today={today}
        />
      )}
      {dialog === "refuse" && (
        <RefuseDialog
          api={api}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onRefused={(refused) => {
            setDialog(null);
            setQuotation(refused);
            setNotice(qt(language, "refused_toast", refused.quotation_number));
          }}
          propertyId={propertyId}
          quotation={quotation}
        />
      )}
    </>
  );
}

function SignDialog({
  language,
  propertyId,
  quotation,
  api,
  productsApi,
  today,
  onClose,
  onSigned,
  onStale,
}: {
  language: Language;
  propertyId: string;
  quotation: Quotation;
  api: QuotationsApi;
  productsApi: Pick<ProductsApi, "locations">;
  today: string;
  onClose: () => void;
  onSigned: (signed: Quotation) => void;
  onStale: () => void;
}) {
  const items = quotation.lines.filter((line) => line.kind === "ITEM");
  const [locations, setLocations] = useState<Locations | null>(
    items.length === 0 ? { places: [], features: [] } : null,
  );
  const [readFailed, setReadFailed] = useState(false);
  const [day, setDay] = useState(today);
  const [takes, setTakes] = useState<Record<number, string>>({});
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const wanted = quotation.lines.filter((line) => line.kind === "ITEM");
    if (wanted.length === 0) return;
    let live = true;
    void productsApi
      .locations(propertyId)
      .then((found) => {
        if (!live) return;
        setLocations(found);
        // Each Item starts at the first place that holds enough of it.
        const start: Record<number, string> = {};
        for (const line of wanted) {
          const place = found.places.find(
            (candidate) => heldAt(candidate, line.product_id) >= line.quantity,
          );
          if (place !== undefined) start[line.position] = placeKey(place);
        }
        setTakes(start);
      })
      .catch(() => {
        if (live) setReadFailed(true);
      });
    return () => {
      live = false;
    };
  }, [productsApi, propertyId, quotation.lines]);

  const places = locations?.places ?? [];
  const byKey = new Map(places.map((place) => [placeKey(place), place]));
  const dayOk = isDay(day) && day >= quotation.made_on && day <= today;
  // What each line still needs from its place, counting the lines above it at the same place.
  const used = new Map<string, number>();
  const lineProblems = new Map<number, string>();
  for (const line of items) {
    const key = takes[line.position];
    const place = key === undefined ? undefined : byKey.get(key);
    if (place === undefined) {
      const anywhere = places.some(
        (candidate) => heldAt(candidate, line.product_id) > 0,
      );
      lineProblems.set(
        line.position,
        anywhere
          ? qt(language, "e_take")
          : qt(language, "no_stock", line.name_en),
      );
      continue;
    }
    const counted = `${placeKey(place)}|${line.product_id}`;
    const before = used.get(counted) ?? 0;
    const held = heldAt(place, line.product_id) - before;
    used.set(counted, before + line.quantity);
    if (held < line.quantity)
      lineProblems.set(
        line.position,
        qt(
          language,
          "e_short",
          String(Math.max(0, held)),
          placeLabel(place, language),
        ),
      );
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setFailure(null);
    if (!dayOk || lineProblems.size > 0 || locations === null) return;
    const chosen: Take[] = items.map((line) => {
      const place = byKey.get(takes[line.position] ?? "");
      return {
        position: line.position,
        unit_id: place?.unit_id ?? "",
        item_id: place?.item_id ?? "",
        number: place?.number ?? 0,
      };
    });
    setBusy(true);
    void api
      .sign(propertyId, quotation, day, chosen)
      .then(onSigned)
      .catch((error: unknown) => {
        setBusy(false);
        if (error instanceof QuotationsError && error.status === 412) {
          onStale();
          return;
        }
        setFailure(
          error instanceof QuotationsError && error.status === 409
            ? qt(language, "f_stock")
            : refusal(language, error),
        );
      });
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={qt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={qt(language, "sign_ok")}
      title={qt(language, "sign_t", quotation.quotation_number)}
      wide
    >
      <div className="ui-tablewrap">
        <table className="ui-table">
          <thead>
            <tr>
              <th scope="col">{qt(language, "col_prod")}</th>
              <th className="r" scope="col">
                {qt(language, "col_qty")}
              </th>
              <th className="r" scope="col">
                {qt(language, "col_price")}
              </th>
              <th className="r" scope="col">
                {qt(language, "col_amt")}
              </th>
            </tr>
          </thead>
          <tbody>
            {quotation.lines.map((line) => (
              <tr key={line.position}>
                <td>{line.name_en}</td>
                <td className="r ui-num">{line.quantity}</td>
                <td className="r ui-num">
                  {usdFromCents(line.price_usd_cents)}
                </td>
                <td className="r ui-num">
                  {usdFromCents(line.amount_usd_cents)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3}>{qt(language, "total")}</td>
              <td className="r ui-num">
                {usdFromCents(quotation.total_usd_cents)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="ui-field">
        <label htmlFor="qs-day">
          {qt(language, "sign_day")}
          <span className="req">{qt(language, "required")}</span>
        </label>
        <DateInput
          describedBy={checked && !dayOk ? "qs-day-err" : undefined}
          id="qs-day"
          invalid={checked && !dayOk}
          language={language}
          max={today}
          min={quotation.made_on}
          onChange={setDay}
          value={day}
        />
        {checked && !dayOk && (
          <p className="ui-error" id="qs-day-err">
            <Icon name="alert" small />
            <span>
              {qt(
                language,
                "e_day",
                dayText(quotation.made_on),
                dayText(today),
              )}
            </span>
          </p>
        )}
      </div>
      {readFailed && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{qt(language, "failed")}</p>
        </div>
      )}
      {items.length > 0 && locations === null && !readFailed && (
        <p className="ui-muted" role="status">
          {qt(language, "loading")}
        </p>
      )}
      {locations !== null &&
        items.map((line) => {
          const id = `qs-take-${String(line.position)}`;
          const problem = checked ? lineProblems.get(line.position) : undefined;
          const holding = places.filter(
            (place) => heldAt(place, line.product_id) > 0,
          );
          return (
            <div className="ui-field" key={line.position}>
              <label htmlFor={id}>
                {qt(language, "take", line.name_en, line.quantity)}
              </label>
              <select
                aria-describedby={
                  problem === undefined ? undefined : `${id}-err`
                }
                aria-invalid={problem !== undefined}
                className="ui-sel"
                id={id}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  setTakes((current) => ({
                    ...current,
                    [line.position]: value,
                  }));
                }}
                value={takes[line.position] ?? ""}
              >
                <option value="">{qt(language, "take_pick")}</option>
                {holding.map((place) => (
                  <option key={placeKey(place)} value={placeKey(place)}>
                    {`${placeLabel(place, language)} · ${qt(
                      language,
                      "in_stock",
                      String(heldAt(place, line.product_id)),
                    )}`}
                  </option>
                ))}
              </select>
              {problem !== undefined && (
                <p className="ui-error" id={`${id}-err`}>
                  <Icon name="alert" small />
                  <span>{problem}</span>
                </p>
              )}
            </div>
          );
        })}
      <div className="ui-notice" role="note">
        <Icon name="invoice" />
        <p>
          {qt(
            language,
            "sign_h",
            usdFromCents(quotation.total_usd_cents),
            quotation.due_days,
          )}
        </p>
      </div>
      {failure !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
    </Dialog>
  );
}

function RefuseDialog({
  language,
  propertyId,
  quotation,
  api,
  onClose,
  onRefused,
}: {
  language: Language;
  propertyId: string;
  quotation: Quotation;
  api: QuotationsApi;
  onClose: () => void;
  onRefused: (refused: Quotation) => void;
}) {
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const empty = reason.trim() === "";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChecked(true);
    setFailure(null);
    if (empty) {
      document.getElementById("qr-reason")?.focus();
      return;
    }
    setBusy(true);
    void api
      .refuse(propertyId, quotation, reason.trim())
      .then(onRefused)
      .catch((error: unknown) => {
        setBusy(false);
        setFailure(refusal(language, error));
      });
  };

  return (
    <Dialog
      busy={busy}
      closeLabel={qt(language, "cancel")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={qt(language, "refuse")}
      title={qt(language, "refuse_t", quotation.quotation_number)}
    >
      <div className="ui-field">
        <label htmlFor="qr-reason">
          {qt(language, "refuse_r")}
          <span className="req">{qt(language, "required")}</span>
        </label>
        <input
          aria-describedby={checked && empty ? "qr-reason-err" : undefined}
          aria-invalid={checked && empty}
          autoComplete="off"
          id="qr-reason"
          maxLength={500}
          onChange={(event) => {
            setReason(event.currentTarget.value);
          }}
          value={reason}
        />
        {checked && empty && (
          <p className="ui-error" id="qr-reason-err">
            <Icon name="alert" small />
            <span>{qt(language, "e_reason")}</span>
          </p>
        )}
      </div>
      {failure !== null && (
        <div className="ui-notice err" role="alert">
          <Icon name="alert" />
          <p>{failure}</p>
        </div>
      )}
    </Dialog>
  );
}
