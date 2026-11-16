// UI v81 module batch 2 (Payments, owner 12/11/2026): the "Exchange rate for riel" card beside
// Receive payment, as in design v81. It shows the rate the app would use now (the server's
// preview of one dollar; nothing is saved) and what each unpaid item costs in riel at that rate,
// so staff can tell a Customer the riel amount before they pay. When the server has no rate the
// card says so. Display only: the app rate and the markup are the server's, and the riel
// amounts use the form's own rounding (the `toRiel` the form passes).

import { usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import type { Language } from "../signInText";
import type { PayableItem } from "./payFor";
import type { KhrRate } from "./paymentsClient";
import { pyt } from "./text";

function riel(value: number): string {
  return `${value.toLocaleString("en-US")} ៛`;
}

/**
 * The published rate with the server's markup, for showing the step between the two rates:
 * "4092.000000" with 50 hundredths of a percent is "4,112.46". Null when the text is not such
 * a number. Shown only; the app rate itself is the server's.
 */
export function markedUp(reference: string, markupBp: number): string | null {
  const match = /^(\d{1,9})(?:\.(\d{1,6}))?$/.exec(reference.trim());
  if (match === null || !Number.isSafeInteger(markupBp) || markupBp < 0)
    return null;
  const [, whole = "0", fraction = ""] = match;
  const millionths =
    Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
  // Thousandths of a riel: millionths × (10,000 + markup) ÷ 10,000 ÷ 1,000.
  const thousandths = Math.round((millionths * (10_000 + markupBp)) / 1e7);
  return (thousandths / 1000).toLocaleString("en-US", {
    maximumFractionDigits: 3,
  });
}

/**
 * A dollar amount times the app rate, before rounding up to whole riel: "184,262.4", and
 * whether it is whole riel already. Shown so staff can see how the riel amount is reached.
 */
export function rielProduct(
  cents: number,
  rate: number,
): { text: string; whole: boolean } {
  const hundredths = cents * rate;
  const whole = Math.floor(hundredths / 100).toLocaleString("en-US");
  const part = hundredths % 100;
  return part === 0
    ? { text: whole, whole: true }
    : {
        text: `${whole}.${String(part).padStart(2, "0").replace(/0$/, "")}`,
        whole: false,
      };
}

/** 50 hundredths of a percent as "0.5". */
export function percentOf(markupBp: number): string {
  return (markupBp / 100).toLocaleString("en-US", {
    maximumFractionDigits: 2,
  });
}

export function RielRateCard({
  language,
  rate,
  when,
  typedCents,
  typedRiel,
  items,
  toRiel,
}: {
  language: Language;
  /** undefined while it is read; null when the server has no rate now. */
  rate: KhrRate | null | undefined;
  /** The published time of the rate, as text ("03/11/2026, 08:00"). */
  when: string | null;
  /** The dollar value typed in the form, when the form is in dollars. */
  typedCents: number | null;
  /** The riel typed in the form, when the form is in riel. */
  typedRiel: { riel: number; cents: number | null } | null;
  /** What the chosen Customer still owes. */
  items: readonly PayableItem[];
  /** The form's own rounding: the riel to pay for a dollar amount at the app rate. */
  toRiel: (cents: number, rate: number) => number;
}) {
  // The step from the published rate to the app rate shows only when the server names both
  // the published rate and a markup above 0. Since DL-228 (PR #35) the app adds no markup, so
  // a new rate has none; only a rate saved before then still carries its 0.5%.
  const marked =
    rate?.reference === undefined ||
    rate.markupBp === undefined ||
    rate.markupBp === 0
      ? null
      : markedUp(rate.reference, rate.markupBp);
  return (
    <section aria-labelledby="rp-fx" className="ui-card">
      <h2 id="rp-fx">{pyt(language, "fx_t")}</h2>
      {rate === undefined ? (
        <p className="ui-muted ui-tight" role="status">
          {pyt(language, "loading")}
        </p>
      ) : rate === null ? (
        <>
          <div className="ui-well">
            <div className="line">
              <span>{pyt(language, "fx_system")}</span>
              <b>{pyt(language, "fx_none")}</b>
            </div>
          </div>
          <p className="ui-small ui-muted ui-tight">
            {pyt(language, "err_rate")}
          </p>
        </>
      ) : (
        <>
          <div className="ui-well ui-fx">
            {rate.reference !== undefined && (
              <div className="line">
                <span>
                  {pyt(language, "fx_aba")}
                  {when !== null && (
                    <span className="ui-sub2 ui-num">
                      {pyt(language, "fx_src", when)}
                    </span>
                  )}
                </span>
                <span className="ui-num">{riel(Number(rate.reference))}</span>
              </div>
            )}
            {rate.markupBp !== undefined && marked !== null && (
              <div className="line">
                <span>
                  {pyt(language, "fx_markup", percentOf(rate.markupBp))}
                </span>
                <span className="ui-num">{marked}</span>
              </div>
            )}
            <div className="line total">
              <b>{pyt(language, "fx_system")}</b>
              <b className="ui-num">{riel(rate.rate)} = $1.00</b>
            </div>
            {typedRiel !== null ? (
              <div className="line">
                <span>{pyt(language, "fx_usd")}</span>
                <b className="ui-num">
                  {typedRiel.cents === null
                    ? "—"
                    : usdFromCents(typedRiel.cents)}
                </b>
              </div>
            ) : (
              typedCents !== null && (
                <div className="line">
                  <span>{pyt(language, "fx_khr_of")}</span>
                  <b className="ui-num">
                    {riel(toRiel(typedCents, rate.rate))}
                  </b>
                </div>
              )
            )}
          </div>
          {items.length > 0 && (
            <ul className="ui-fxpay">
              {items.map((item) => {
                const product = rielProduct(item.owed, rate.rate);
                return (
                  <li key={item.id}>
                    <span>
                      {pyt(language, "fx_pay", usdFromCents(item.owed))} ·{" "}
                      <span className="ui-num">
                        {item.kind === "INVOICE"
                          ? item.invoiceNumber
                          : pyt(language, "pfl_d", item.invoiceNumber)}
                      </span>
                    </span>
                    <b className="ui-num">
                      {riel(toRiel(item.owed, rate.rate))}
                    </b>
                    <small className="ui-num">
                      {pyt(
                        language,
                        product.whole ? "fx_calc" : "fx_calc_up",
                        usdFromCents(item.owed),
                        riel(rate.rate),
                        `${product.text} ៛`,
                      )}
                    </small>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="ui-small ui-muted ui-tight ui-fxnote">
            <Icon name="lock" small />
            <span>
              {pyt(language, "fx_note")} {pyt(language, "fx_usd_note")}
            </span>
          </p>
        </>
      )}
    </section>
  );
}
