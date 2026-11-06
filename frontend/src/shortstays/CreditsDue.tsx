// Daily and weekly rent, phase 6 step 5d: late-cancel credits past their use-by day
// (migration 20270609_319). The owner chose on 05/11/2026 that an unused credit ends and what
// is left becomes income. The list shows them to the credit right; the booking ends each one.

import { useEffect, useState } from "react";

import { dayText, usdFromCents } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import type { CreditDue, ShortStaysApi } from "./shortStaysClient";
import { st } from "./text";

export function CreditsDue({
  language,
  propertyId,
  api,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
}) {
  const [due, setDue] = useState<CreditDue[]>([]);

  useEffect(() => {
    let live = true;
    void api
      .creditsDue(propertyId)
      .then((found) => {
        if (live) setDue(found);
      })
      .catch(() => {
        // The list still works; the credits show again on the next visit.
        if (live) setDue([]);
      });
    return () => {
      live = false;
    };
  }, [api, propertyId]);

  if (due.length === 0) return null;
  return (
    <section aria-labelledby="ss-credits-due" className="ui-notice warn">
      <Icon name="alert" />
      <div>
        <h2 className="ui-small" id="ss-credits-due">
          {st(language, "cd_t", due.length)}
        </h2>
        <ul className="ss-due">
          {due.map((entry) => (
            <li key={entry.booking_id}>
              <a href={hashForPage("shortstays", `st:${entry.booking_id}`)}>
                {entry.booking_number}
              </a>{" "}
              ·{" "}
              {st(
                language,
                "cd_row",
                entry.guest_name,
                usdFromCents(entry.left_usd_cents),
                dayText(entry.use_by),
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
