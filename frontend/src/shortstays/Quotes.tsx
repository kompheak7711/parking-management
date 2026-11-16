// Daily and weekly rent, phase 6 step 5b: a quote (SQ…, migration 20270607_317) is today's price
// for a room and nights, with a message for the guest's Telegram. A quote is not a promise: the
// booking is priced when it is made. Leasing batch (owner 13/11/2026): the Quotes tab is gone;
// New booking's "Copy price message" makes the quote and copies this message.

import { dayText, usdFromCents } from "../shell/format";
import type { Language } from "../signInText";
import { nightsText, unitTypeText } from "./ShortStaysPage";
import type { StayQuote } from "./shortStaysClient";
import { timeText } from "./StaySteps";
import { st } from "./text";

/** The message for the guest, in the screen's language. */
export function quoteMessage(language: Language, quote: StayQuote): string {
  const month =
    quote.month_only_usd_cents === null || quote.monthly_rent_usd_cents === null
      ? ""
      : `\n${st(
          language,
          "q_month",
          usdFromCents(quote.month_only_usd_cents),
          usdFromCents(quote.monthly_rent_usd_cents),
        )}`;
  return `${st(
    language,
    "q_message",
    quote.quote_number,
    `${quote.unit_number ?? ""} (${unitTypeText(language, quote.unit_type)})`,
    quote.guest_count,
    dayText(quote.check_in_on),
    dayText(quote.check_out_on),
    nightsText(language, quote.nights),
    usdFromCents(quote.total_usd_cents),
    timeText(quote.check_in_time),
    timeText(quote.check_out_time),
    usdFromCents(quote.deposit_usd_cents),
  )}${month}`;
}
