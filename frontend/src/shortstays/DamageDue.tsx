// DL-222 (migration 20270716_391): the stays whose room check reported problems and whose damage
// is not decided yet. The list shows them to the person who bills damage; the booking decides
// each one (Charge the guest or No charge), and the deposit waits until then.

import { useEffect, useState } from "react";

import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import type { DamageDue as Due, ShortStaysApi } from "./shortStaysClient";
import { st } from "./text";

export function DamageDue({
  language,
  propertyId,
  api,
}: {
  language: Language;
  propertyId: string;
  api: ShortStaysApi;
}) {
  const [due, setDue] = useState<Due[]>([]);

  useEffect(() => {
    let live = true;
    void api
      .damageDue(propertyId)
      .then((found) => {
        if (live) setDue(found);
      })
      .catch(() => {
        // The list still works; the stays show again on the next visit.
        if (live) setDue([]);
      });
    return () => {
      live = false;
    };
  }, [api, propertyId]);

  if (due.length === 0) return null;
  return (
    <section aria-labelledby="ss-damage-due" className="ui-notice warn">
      <Icon name="alert" />
      <div>
        <h2 className="ui-small" id="ss-damage-due">
          {st(language, "dd_t", due.length)}
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
                "dd_row",
                entry.guest_name,
                entry.unit_number,
                entry.problem_count,
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
