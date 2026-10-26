// V1-058 R3: the Leases list (DESIGN.md "Leases (round 2)"): four count cards that filter the
// table, and the table of Leases.

import { useState } from "react";

import type { LeaseResource } from "../leaseClient";
import { dayText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  DepositCell,
  LeaseCard,
  LeaseKind,
  LeasesData,
  cardsOf,
  endingLimit,
  kindOf,
  renewedIds,
  sortLeases,
} from "./leasesData";
import { lt } from "./text";

const KIND_CHIPS: Record<LeaseKind, [Tone, ShellIcon | undefined]> = {
  current: ["ok", "check"],
  ending: ["warn", "clock"],
  draft: ["info", "lease"],
  ended: ["neutral", undefined],
  terminated: ["err", "x"],
  cancelled: ["neutral", "x"],
};

export function LeaseChip({
  language,
  kind,
}: {
  language: Language;
  kind: LeaseKind;
}) {
  const [tone, icon] = KIND_CHIPS[kind];
  return (
    <Chip icon={icon} tone={tone}>
      {lt(language, `k_${kind}`)}
    </Chip>
  );
}

const CARDS: [LeaseCard, ShellIcon, Tone | "brand"][] = [
  ["current", "check", "ok"],
  ["ending", "clock", "warn"],
  ["draft", "lease", "info"],
  ["ended", "x", "neutral"],
];

function DepositText({
  language,
  cell,
}: {
  language: Language;
  cell: DepositCell | undefined;
}) {
  if (cell?.state !== "shown") return <span className="ui-muted">—</span>;
  return (
    <>
      {usdFromCents(cell.received)}
      <span className="ui-sub2">
        {lt(language, "of", usdFromCents(cell.required))}
      </span>
    </>
  );
}

export function LeasesList({
  language,
  canCreate,
  data,
  deposits,
  today,
}: {
  language: Language;
  canCreate: boolean;
  data: LeasesData;
  deposits: Map<string, DepositCell> | null;
  today: string;
}) {
  const [card, setCard] = useState<LeaseCard | "all">("all");
  const renewed = renewedIds(data.leases);
  const kind = (lease: LeaseResource) =>
    kindOf(lease, today, renewed.has(lease.lease_id));
  const inCard = (lease: LeaseResource, value: LeaseCard) =>
    cardsOf(kind(lease)).includes(value);
  const sorted = sortLeases(data.leases, today);
  const shown = sorted.filter((lease) => card === "all" || inCard(lease, card));
  const open = (id: string) => {
    openPageInAddress("leases", false, id);
  };

  return (
    <>
      <div className="ui-head">
        <p>{lt(language, "sub")}</p>
        {canCreate && (
          <div className="ui-actions">
            <a className="ui-btn primary" href={hashForPage("leases", "new")}>
              <Icon name="lease" />
              {lt(language, "new_lease")}
            </a>
          </div>
        )}
      </div>
      <div className="ui-kpis">
        {CARDS.map(([value, icon, tone]) => (
          <CountCard
            icon={icon}
            key={value}
            label={lt(language, `c_${value}`)}
            note={lt(language, `c_${value}_s`, dayText(endingLimit(today)))}
            onPress={() => {
              setCard(card === value ? "all" : value);
            }}
            pressed={card === value}
            tone={tone}
            value={data.leases.filter((lease) => inCard(lease, value)).length}
          />
        ))}
      </div>
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {lt(language, "showing", lt(language, `c_${card}`))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {lt(language, "show_all")}
            </button>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">{lt(language, "none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{lt(language, "unit")}</th>
                    <th scope="col">{lt(language, "primary")}</th>
                    <th scope="col">{lt(language, "period")}</th>
                    <th className="r" scope="col">
                      {lt(language, "rent")}
                    </th>
                    <th className="r" scope="col">
                      {lt(language, "deposit_short")}
                    </th>
                    <th scope="col">{lt(language, "status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((lease) => {
                    const id = lease.lease_id;
                    const others = lease.signers.filter(
                      (signer) => !signer.is_primary_tenant,
                    ).length;
                    const terminated = lease.actual_termination_date;
                    return (
                      <tr
                        className="ui-row"
                        key={id}
                        onClick={() => {
                          open(id);
                        }}
                      >
                        <td>
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("leases", id)}
                            onClick={(event) => {
                              event.stopPropagation();
                              // A plain click opens the Lease here; with a key held the
                              // browser opens the link as it normally does.
                              if (
                                event.button !== 0 ||
                                event.metaKey ||
                                event.ctrlKey ||
                                event.shiftKey ||
                                event.altKey
                              )
                                return;
                              event.preventDefault();
                              open(id);
                            }}
                          >
                            {lease.unit_number}
                          </a>
                        </td>
                        <td>
                          {lease.primary_tenant_name}
                          {others > 0 && (
                            <span className="ui-sub2">
                              {lt(language, "plus_signers", others)}
                            </span>
                          )}
                        </td>
                        <td className="ui-num">
                          {lt(
                            language,
                            "dash",
                            dayText(lease.start_date),
                            dayText(lease.end_date),
                          )}
                          {terminated !== null && (
                            <span className="ui-sub2 warn">
                              {lt(language, "ended_on", dayText(terminated))}
                            </span>
                          )}
                        </td>
                        <td className="r ui-num">
                          {lease.monthly_rent_usd_cents === null ? (
                            <span className="ui-muted">—</span>
                          ) : (
                            usdFromCents(lease.monthly_rent_usd_cents)
                          )}
                        </td>
                        <td className="r ui-num">
                          <DepositText
                            cell={deposits?.get(id)}
                            language={language}
                          />
                        </td>
                        <td>
                          <LeaseChip kind={kind(lease)} language={language} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {shown.length === 1
                ? lt(language, "n1")
                : lt(language, "n", shown.length)}
            </div>
          </>
        )}
      </div>
    </>
  );
}
