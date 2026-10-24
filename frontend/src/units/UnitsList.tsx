// V1-058 R2: the Units list (DESIGN.md "Units (round 2)"): a floor segment, a Unit Type
// select, four count cards that filter the table, and the table of Units.

import { useState } from "react";

import { dayText, usdFromCents } from "../shell/format";
import { Icon, type ShellIcon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, CountCard, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitStatus } from "../unitClient";
import { ut } from "./text";
import {
  UnitCard,
  UnitsData,
  cardOf,
  leaseFor,
  reservationFor,
  typeName,
} from "./unitsData";

const STATUS_CHIPS: Record<UnitStatus, [Tone, ShellIcon | undefined]> = {
  OCCUPIED: ["ok", "check"],
  RESERVED: ["info", "calendar"],
  VACANT: ["neutral", undefined],
  CLEANING: ["warn", undefined],
  UNDER_MAINTENANCE: ["warn", "wrench"],
  OUT_OF_SERVICE: ["err", "alert"],
};

export function UnitChip({
  language,
  status,
}: {
  language: Language;
  status: UnitStatus;
}) {
  const [tone, icon] = STATUS_CHIPS[status];
  return (
    <Chip icon={icon} tone={tone}>
      {ut(language, `s_${status}`)}
    </Chip>
  );
}

/** A floor named only by its number shows as "Floor 2". */
export function floorText(language: Language, floor: string): string {
  return /^\d+$/.test(floor) ? ut(language, "floor_n", floor) : floor;
}

const CARDS: [UnitCard, ShellIcon, Tone | "brand"][] = [
  ["occupied", "check", "ok"],
  ["reserved", "calendar", "info"],
  ["vacant", "door", "brand"],
  ["na", "wrench", "warn"],
];

export function UnitsList({
  language,
  data,
  onNewUnit,
}: {
  language: Language;
  data: UnitsData;
  /** Null when the person may not add Units or the Settings lists are missing. */
  onNewUnit: (() => void) | null;
}) {
  const khmer = language === "km";
  const [floor, setFloor] = useState("all");
  const [type, setType] = useState("all");
  const [card, setCard] = useState<UnitCard | "all">("all");

  // Floors in the Settings order, then any floor a Unit uses that is not in the list.
  const floorOrder = (data.lists?.lists.FLOOR ?? []).map(
    (item) => item.name_en,
  );
  const floors = [...new Set(data.units.map((unit) => unit.floor))].sort(
    (left, right) => {
      const a = floorOrder.indexOf(left);
      const b = floorOrder.indexOf(right);
      if (a !== b) return (a < 0 ? 1e9 : a) - (b < 0 ? 1e9 : b);
      return left.localeCompare(right, undefined, { numeric: true });
    },
  );
  const types = [
    ...new Set([
      ...(data.lists?.lists.UNIT_TYPE ?? [])
        .filter((item) => !item.removed)
        .map((item) => item.code),
      ...data.units.map((unit) => unit.unit_type),
    ]),
  ];
  const base = data.units.filter(
    (unit) =>
      (floor === "all" || unit.floor === floor) &&
      (type === "all" || unit.unit_type === type),
  );
  const shown = base.filter(
    (unit) => card === "all" || cardOf(unit.status) === card,
  );
  const unknown = data.leases === null || data.reservations === null;
  const dash = <span className="ui-muted">—</span>;

  return (
    <>
      <div className="ui-head">
        <p>{ut(language, "sub", data.units.length)}</p>
        {onNewUnit !== null && (
          <div className="ui-actions">
            <button
              className="ui-btn primary"
              onClick={onNewUnit}
              type="button"
            >
              <Icon name="plus" />
              {ut(language, "new_unit")}
            </button>
          </div>
        )}
      </div>
      <div className="ui-filters">
        <div aria-label={ut(language, "floor")} className="ui-seg" role="group">
          {["all", ...floors].map((value) => (
            <button
              aria-pressed={floor === value}
              key={value}
              onClick={() => {
                setFloor(value);
              }}
              type="button"
            >
              {value === "all"
                ? ut(language, "all_floors")
                : floorText(language, value)}
            </button>
          ))}
        </div>
        <label className="ui-sr" htmlFor="units-type">
          {ut(language, "type")}
        </label>
        <select
          className="ui-sel"
          id="units-type"
          onChange={(event) => {
            setType(event.currentTarget.value);
          }}
          value={type}
        >
          <option value="all">{ut(language, "all_types")}</option>
          {types.map((code) => (
            <option key={code} value={code}>
              {typeName(data.lists, code, khmer)}
            </option>
          ))}
        </select>
      </div>
      <div className="ui-kpis">
        {CARDS.map(([value, icon, tone]) => (
          <CountCard
            icon={icon}
            key={value}
            label={ut(language, `c_${value}`)}
            note={ut(language, `c_${value}_s`)}
            onPress={() => {
              setCard(card === value ? "all" : value);
            }}
            pressed={card === value}
            tone={tone}
            value={base.filter((unit) => cardOf(unit.status) === value).length}
          />
        ))}
      </div>
      {unknown && (
        <div className="ui-notice">
          <Icon name="info" />
          <p>{ut(language, "tenants_hidden")}</p>
        </div>
      )}
      <div className="ui-card pad0">
        {card !== "all" && (
          <div className="ui-listbar">
            {ut(language, "showing", ut(language, `c_${card}`))}
            <button
              className="ui-btn link"
              onClick={() => {
                setCard("all");
              }}
              type="button"
            >
              {ut(language, "show_all")}
            </button>
          </div>
        )}
        {shown.length === 0 ? (
          <p className="ui-empty">{ut(language, "none")}</p>
        ) : (
          <>
            <div className="ui-tablewrap">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">{ut(language, "col_unit")}</th>
                    <th scope="col">{ut(language, "floor")}</th>
                    <th scope="col">{ut(language, "type")}</th>
                    <th scope="col">{ut(language, "col_status")}</th>
                    <th scope="col">{ut(language, "col_customer")}</th>
                    <th className="r" scope="col">
                      {ut(language, "rent")}
                    </th>
                    <th scope="col">{ut(language, "until")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((unit) => {
                    const lease = leaseFor(data, unit.unit_id);
                    const reservation =
                      lease === null
                        ? reservationFor(data, unit.unit_id)
                        : null;
                    const others = (lease?.signers.length ?? 1) - 1;
                    return (
                      <tr
                        className="ui-row"
                        key={unit.unit_id}
                        onClick={() => {
                          openPageInAddress("units", false, unit.unit_id);
                        }}
                      >
                        <td>
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("units", unit.unit_id)}
                            onClick={(event) => {
                              event.stopPropagation();
                              // A plain click opens the Unit here; with a key held the
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
                              openPageInAddress("units", false, unit.unit_id);
                            }}
                          >
                            {unit.unit_number}
                          </a>
                        </td>
                        <td>{floorText(language, unit.floor)}</td>
                        <td>{typeName(data.lists, unit.unit_type, khmer)}</td>
                        <td>
                          <UnitChip language={language} status={unit.status} />
                        </td>
                        <td>
                          {lease !== null
                            ? lease.primary_tenant_name
                            : reservation !== null
                              ? reservation.customer_name
                              : dash}
                          {others > 0 && (
                            <span className="ui-sub2">
                              {ut(language, "signers_n", others)}
                            </span>
                          )}
                        </td>
                        <td className="r ui-num">
                          {lease?.monthly_rent_usd_cents != null ? (
                            usdFromCents(lease.monthly_rent_usd_cents)
                          ) : reservation !== null ? (
                            <>
                              {usdFromCents(
                                reservation.agreed_monthly_rent_usd_cents,
                              )}
                              <span className="ui-sub2">
                                {ut(language, "agreed")}
                              </span>
                            </>
                          ) : (
                            dash
                          )}
                        </td>
                        <td className="ui-num">
                          {lease?.end_date != null ? (
                            dayText(lease.end_date)
                          ) : reservation !== null ? (
                            <>
                              {dayText(reservation.effective_expiration_date)}
                              <span className="ui-sub2">
                                {ut(language, "reserved_until")}
                              </span>
                            </>
                          ) : (
                            dash
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="ui-tfoot">
              {shown.length === 1
                ? ut(language, "n1")
                : ut(language, "n", shown.length)}
            </div>
          </>
        )}
      </div>
    </>
  );
}
