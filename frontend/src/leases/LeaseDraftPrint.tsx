// V1-060 B6 (owner 27/10/2026, DL-100): Print draft. After drafting, the customer checks the
// draft on paper before paying: the Unit, the people, the dates, the Rent, the Security Deposit,
// the Services and the money paid at signing. Printing shows only the sheet (A4).

import { FormEvent, useEffect, useState } from "react";

import type { LeaseResource } from "../leaseClient";
import type { SettlementApi, SigningPreview } from "../settlementClient";
import { dayText, todayInPhnomPenh, usdFromCents } from "../shell/format";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import { lt } from "./text";

/** Prints only the sheet (screens.css .lease-print), then the page is as before. */
function printSheet() {
  document.body.classList.add("ui-printing");
  const done = () => {
    document.body.classList.remove("ui-printing");
  };
  window.addEventListener("afterprint", done, { once: true });
  window.print();
}

export function LeaseDraftPrint({
  language,
  lease,
  signingApi,
  onClose,
}: {
  language: Language;
  lease: LeaseResource;
  signingApi: Pick<SettlementApi, "signingPreview">;
  onClose: () => void;
}) {
  const [preview, setPreview] = useState<SigningPreview | "failed" | null>(
    null,
  );
  useEffect(() => {
    let live = true;
    signingApi
      .signingPreview(lease.lease_id)
      .then((value) => {
        if (live) setPreview(value);
      })
      .catch(() => {
        if (live) setPreview("failed");
      });
    return () => {
      live = false;
    };
  }, []);

  const initial =
    preview !== null && preview !== "failed" ? preview.initial : null;
  const planned =
    preview !== null && preview !== "failed"
      ? preview.planned_security_deposit_usd_cents
      : null;
  const walkIn =
    lease.predecessor_lease_id === null && lease.security_deposit_id === null;
  const others = lease.signers.filter((signer) => !signer.is_primary_tenant);
  const rows: [string, string][] = [
    [lt(language, "lp_unit"), lease.unit_number],
    [lt(language, "lp_tenant"), lease.primary_tenant_name],
    ...(others.length > 0
      ? ([
          [
            lt(language, "lp_signers"),
            others.map((signer) => signer.customer_name).join(", "),
          ],
        ] as [string, string][])
      : []),
    [
      lt(language, "lp_dates"),
      lt(
        language,
        "from_to",
        dayText(lease.start_date),
        dayText(lease.end_date),
      ),
    ],
    [
      lt(language, "lp_rent"),
      lease.monthly_rent_usd_cents === null
        ? "—"
        : usdFromCents(lease.monthly_rent_usd_cents),
    ],
    [
      lt(language, "sp_deposit"),
      !walkIn
        ? lt(
            language,
            lease.predecessor_lease_id === null
              ? "lp_dep_booking"
              : "lp_dep_renewal",
          )
        : planned === null
          ? "—"
          : usdFromCents(planned),
    ],
    ...(lease.pet_deposit_required
      ? ([[lt(language, "lp_pet"), lease.pet_description ?? ""]] as [
          string,
          string,
        ][])
      : []),
  ];

  function print(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    printSheet();
  }

  return (
    <Dialog
      closeLabel={lt(language, "close")}
      onClose={onClose}
      onSubmit={print}
      submitLabel={lt(language, "lp_print")}
      title={lt(language, "lp_title", lease.unit_number)}
      wide
    >
      <article className="lease-print" aria-label={lt(language, "lp_sheet")}>
        <h2>{lt(language, "lp_heading")}</h2>
        <p className="lease-print-note">
          {lt(language, "lp_note", dayText(todayInPhnomPenh()))}
        </p>
        <dl className="ui-kv">
          {rows.map(([term, value]) => (
            <div key={term} style={{ display: "contents" }}>
              <dt>{term}</dt>
              <dd className="ui-num">{value}</dd>
            </div>
          ))}
        </dl>
        <h3>{lt(language, "lp_at_signing")}</h3>
        {preview === null ? (
          <p className="ui-muted">{lt(language, "sp_loading")}</p>
        ) : preview === "failed" || initial === null ? (
          <p className="ui-muted">{lt(language, "lp_no_amounts")}</p>
        ) : (
          <table className="ui-table ui-num">
            <tbody>
              {walkIn && planned !== null && (
                <tr>
                  <td>{lt(language, "sp_deposit")}</td>
                  <td>{usdFromCents(planned)}</td>
                </tr>
              )}
              <tr>
                <td>
                  {lt(
                    language,
                    "sp_rent",
                    dayText(initial.period_start),
                    dayText(initial.period_end),
                  )}
                </td>
                <td>{usdFromCents(initial.rent_usd_cents)}</td>
              </tr>
              {initial.service_lines.map((line) => (
                <tr key={`${line.name}/${line.period_start}`}>
                  <td>
                    {lt(
                      language,
                      "sp_service",
                      line.name,
                      dayText(line.period_start),
                      dayText(line.period_end),
                    )}
                  </td>
                  <td>{usdFromCents(line.amount_usd_cents)}</td>
                </tr>
              ))}
              {walkIn && planned !== null && (
                <tr>
                  <th scope="row">{lt(language, "sp_total")}</th>
                  <th>{usdFromCents(planned + initial.total_usd_cents)}</th>
                </tr>
              )}
            </tbody>
          </table>
        )}
        <p className="lease-print-sign">{lt(language, "lp_checked")}</p>
      </article>
    </Dialog>
  );
}
