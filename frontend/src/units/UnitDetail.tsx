// V1-058 R2: the Unit page (DESIGN.md "Units (round 2)", owner 13/10/2026 18:08). Left: Unit
// details with the photo place, fact tiles, notes and the inventory. Right: Current Lease,
// Reservation or Availability; Lease history; Meters; Invoices for this Unit; History.
// V1-060 B6 (DL-107, owner 28/10/2026): each button opens its own place: New Lease opens the New
// Lease form with this Unit chosen (or the draft from its Booking), and Open Lease, Open draft
// Lease and Open Reservation open that record, not the list.

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { UnitInventoryPanel } from "../UnitInventoryPanel";
import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { ReservationResource } from "../reservationClient";
import {
  dayText,
  momentText,
  todayInPhnomPenh,
  usdFromCents,
} from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  UnitApi,
  UnitResource,
  UnitSetupLists,
  UnitTimelineEvent,
} from "../unitClient";
import { ChangeStatusDialog, UpdateUnitDialog } from "./UnitDialogs";
import { UnitChip, floorText } from "./UnitsList";
import { ut } from "./text";
import { itemName, typeName } from "./unitsData";

type LeaseKind = "current" | "draft" | "ended" | "terminated" | "cancelled";

function leaseKind(lease: LeaseResource, today: string): LeaseKind {
  if (lease.status === "DRAFTED") return "draft";
  if (lease.status === "CANCELLED") return "cancelled";
  if (lease.status === "TERMINATED") return "terminated";
  return lease.end_date !== null && lease.end_date < today
    ? "ended"
    : "current";
}

const LEASE_CHIPS: Record<LeaseKind, [Tone, "check" | undefined]> = {
  current: ["ok", "check"],
  draft: ["info", undefined],
  ended: ["neutral", undefined],
  terminated: ["neutral", undefined],
  cancelled: ["neutral", undefined],
};

function LeaseChip({
  language,
  lease,
  today,
}: {
  language: Language;
  lease: LeaseResource;
  today: string;
}) {
  const kind = leaseKind(lease, today);
  const [tone, icon] = LEASE_CHIPS[kind];
  return (
    <Chip icon={icon} tone={tone}>
      {ut(language, `lk_${kind}`)}
    </Chip>
  );
}

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ui-kv">
      {rows.map(([term, value]) => (
        <div key={term} style={{ display: "contents" }}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function period(lease: LeaseResource): string {
  return `${dayText(lease.start_date)} – ${dayText(lease.end_date)}`;
}

function money(cents: number | null): string {
  return cents === null ? "—" : usdFromCents(cents);
}

interface HistoryLine {
  at: string;
  text: string;
}

/** The Unit's own audit events, with the Lease and Reservation steps for this Unit. */
function historyLines(
  language: Language,
  events: UnitTimelineEvent[],
  leases: LeaseResource[],
  reservation: ReservationResource | null,
): HistoryLine[] {
  const lines: HistoryLine[] = [];
  for (const event of events) {
    if (event.action === "unit.created") {
      lines.push({ at: event.occurred_at, text: ut(language, "h_created") });
    } else if (event.action === "unit.inventory_updated") {
      lines.push({ at: event.occurred_at, text: ut(language, "h_inventory") });
    } else if (event.action === "unit.status_changed") {
      const state = event.resulting_state as { status?: string } | null;
      const status = state?.status ?? "";
      const name = (
        [
          "VACANT",
          "RESERVED",
          "OCCUPIED",
          "CLEANING",
          "UNDER_MAINTENANCE",
          "OUT_OF_SERVICE",
        ] as const
      ).find((value) => value === status);
      lines.push({
        at: event.occurred_at,
        text: ut(
          language,
          "h_status",
          name === undefined ? status : ut(language, `s_${name}`),
          event.reason,
        ),
      });
    } else {
      lines.push({ at: event.occurred_at, text: ut(language, "h_updated") });
    }
  }
  for (const lease of leases) {
    if (lease.signed_at !== null)
      lines.push({
        at: lease.signed_at,
        text: ut(language, "h_signed", lease.primary_tenant_name),
      });
    for (const occupancy of lease.occupancies) {
      lines.push({
        at: occupancy.move_in_date,
        text: ut(language, "h_movein", occupancy.customer_name),
      });
      if (occupancy.move_out_date !== null)
        lines.push({
          at: occupancy.move_out_date,
          text: ut(language, "h_moveout", occupancy.customer_name),
        });
    }
    if (lease.terminated_at !== null)
      lines.push({
        at: lease.terminated_at,
        text: ut(
          language,
          "h_terminated",
          lease.primary_tenant_name,
          dayText(lease.actual_termination_date),
        ),
      });
  }
  if (reservation !== null)
    lines.push({
      at: reservation.reservation_date,
      text: ut(
        language,
        "h_reserved",
        reservation.customer_name,
        dayText(reservation.effective_expiration_date),
      ),
    });
  // Newest first; a date without a time sorts as the start of that day.
  return lines.sort((left, right) => right.at.localeCompare(left.at));
}

function when(value: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? dayText(value) : momentText(value);
}

export interface UnitDetailProps {
  language: Language;
  unitId: string;
  propertyId: string;
  unitApi: UnitApi;
  leaseApi: LeaseApi;
  lists: UnitSetupLists | null;
  canManage: boolean;
  /** The active Reservation of this Unit from the list, or null. */
  reservation: ReservationResource | null;
  /** False when the person may not read Leases or Reservations. */
  tenanciesKnown: boolean;
  capabilities: ReadonlySet<string> | null;
  onChanged: (unit: UnitResource) => void;
}

export function UnitDetail({
  language,
  unitId,
  propertyId,
  unitApi,
  leaseApi,
  lists,
  canManage,
  reservation,
  tenanciesKnown,
  capabilities,
  onChanged,
}: UnitDetailProps) {
  const khmer = language === "km";
  const [unit, setUnit] = useState<UnitResource | null>(null);
  const [missing, setMissing] = useState(false);
  const [events, setEvents] = useState<UnitTimelineEvent[]>([]);
  const [leases, setLeases] = useState<LeaseResource[] | null>(null);
  const [dialog, setDialog] = useState<"update" | "status" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const sequence = useRef(0);
  const today = todayInPhnomPenh();
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    void Promise.all([
      unitApi.get(unitId),
      unitApi.timeline(unitId).catch(() => null),
      leaseApi.list(propertyId, { unit_id: unitId }).catch(() => null),
    ])
      .then(([loaded, timeline, unitLeases]) => {
        if (operation !== sequence.current) return;
        setUnit(loaded);
        setMissing(false);
        setEvents(timeline?.items ?? []);
        setLeases(unitLeases?.items ?? null);
      })
      .catch(() => {
        if (operation === sequence.current) setMissing(true);
      });
  }, [leaseApi, propertyId, unitApi, unitId]);

  useEffect(() => {
    setUnit(null);
    setNotice(null);
    setDialog(null);
    load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("units");
      }}
      type="button"
    >
      <Icon name="back" small />
      {ut(language, "back")}
    </button>
  );

  if (missing) {
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ut(language, "unit_missing")}</p>
        </div>
      </>
    );
  }
  if (unit === null) {
    return (
      <>
        {back}
        <p className="ui-muted" role="status">
          {ut(language, "loading")}
        </p>
      </>
    );
  }

  const current =
    leases?.find((lease) => leaseKind(lease, today) === "current") ?? null;
  const draft = leases?.find((lease) => lease.status === "DRAFTED") ?? null;
  const past = (leases ?? [])
    .filter((lease) => lease !== current && lease.status !== "DRAFTED")
    .sort((left, right) =>
      (right.start_date ?? "").localeCompare(left.start_date ?? ""),
    );
  const manage = canManage && unit.can_manage !== false && lists !== null;
  const canLease =
    ["VACANT", "CLEANING", "UNDER_MAINTENANCE"].includes(unit.status) ||
    (unit.status === "RESERVED" && reservation !== null && draft === null);
  const type = typeName(lists, unit.unit_type, khmer);
  const sub = [
    floorText(language, unit.floor),
    type,
    unit.size_square_metres === null
      ? null
      : ut(language, "m2", Number(unit.size_square_metres)),
    "CHETANA Parking",
  ]
    .filter((part) => part !== null)
    .join(" · ");

  const fact = (label: string, value: ReactNode) => (
    <div className="ui-fact" key={label}>
      <small>{label}</small>
      <b>{value}</b>
    </div>
  );
  const notRecorded = ut(language, "not_recorded");
  const features =
    lists?.lists.ROOM_FEATURE.filter(
      (item) => !item.removed || unit.room_feature_ids.includes(item.item_id),
    ) ?? [];

  let now: ReactNode;
  if (current !== null) {
    const occupants = current.occupancies.filter(
      (occupancy) => occupancy.move_out_date === null,
    );
    now = (
      <section aria-labelledby="unit-now" className="ui-card">
        <div className="ui-chead">
          <h2 id="unit-now">{ut(language, "current_lease")}</h2>
          <LeaseChip language={language} lease={current} today={today} />
        </div>
        <Kv
          rows={[
            [ut(language, "primary"), current.primary_tenant_name],
            [
              ut(language, "period"),
              <span className="ui-num">{period(current)}</span>,
            ],
            [
              ut(language, "rent"),
              <span className="ui-num">
                {money(current.monthly_rent_usd_cents)}
              </span>,
            ],
            [
              ut(language, "signers"),
              current.signers.map((signer) => signer.customer_name).join(", "),
            ],
            [
              ut(language, "occupants"),
              occupants.length === 0 ? (
                <span className="ui-muted">{ut(language, "no_movein")}</span>
              ) : (
                occupants.map((occupancy) => occupancy.customer_name).join(", ")
              ),
            ],
          ]}
        />
        {may("leases.read") && (
          <div className="ui-qa">
            <a
              className="ui-btn"
              href={hashForPage("leases", current.lease_id)}
            >
              <Icon name="lease" />
              {ut(language, "open_lease")}
            </a>
          </div>
        )}
      </section>
    );
  } else if (reservation !== null) {
    now = (
      <section aria-labelledby="unit-now" className="ui-card">
        <div className="ui-chead">
          <h2 id="unit-now">{ut(language, "reservation")}</h2>
          <Chip icon="check" tone="ok">
            {ut(language, "rs_active")}
          </Chip>
        </div>
        <Kv
          rows={[
            [ut(language, "customer"), reservation.customer_name],
            [
              ut(language, "reserved_on"),
              <span className="ui-num">
                {dayText(reservation.reservation_date)}
              </span>,
            ],
            [
              ut(language, "expires"),
              <span className="ui-num">
                {dayText(reservation.effective_expiration_date)}
              </span>,
            ],
            [
              ut(language, "agreed_rent"),
              <span className="ui-num">
                {usdFromCents(reservation.agreed_monthly_rent_usd_cents)}
              </span>,
            ],
            [
              ut(language, "deposit_received"),
              <span className="ui-num">
                {usdFromCents(reservation.deposit_received_usd_cents)}{" "}
                <span className="ui-muted">
                  / {usdFromCents(reservation.deposit_required_usd_cents)}
                </span>
              </span>,
            ],
          ]}
        />
        {may("reservations.read") && (
          <div className="ui-qa">
            <a
              className="ui-btn"
              href={hashForPage("reservations", reservation.reservation_id)}
            >
              <Icon name="calendar" />
              {ut(language, "open_reservation")}
            </a>
          </div>
        )}
      </section>
    );
  } else {
    const key =
      !tenanciesKnown &&
      (unit.status === "OCCUPIED" || unit.status === "RESERVED")
        ? "a_unknown"
        : unit.status === "CLEANING" ||
            unit.status === "UNDER_MAINTENANCE" ||
            unit.status === "OUT_OF_SERVICE"
          ? (`a_${unit.status}` as const)
          : "a_VACANT";
    now = (
      <section aria-labelledby="unit-now" className="ui-card">
        <h2 id="unit-now">{ut(language, "availability")}</h2>
        <p>{ut(language, key)}</p>
      </section>
    );
  }

  const history = historyLines(language, events, leases ?? [], reservation);

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2 className="ui-num">{unit.unit_number}</h2>
            <UnitChip language={language} status={unit.status} />
          </div>
          <p>{sub}</p>
        </div>
        <div className="ui-actions">
          {unit.status === "VACANT" && may("reservations.create") && (
            <a
              className="ui-btn primary"
              href={hashForPage("reservations", `new:${unit.unit_id}`)}
            >
              <Icon name="calendar" />
              {ut(language, "make_reservation")}
            </a>
          )}
          {canLease && may("leases.draft") && (
            <a
              className={unit.status === "VACANT" ? "ui-btn" : "ui-btn primary"}
              href={hashForPage(
                "leases",
                reservation === null
                  ? `unit:${unit.unit_id}`
                  : `new:${reservation.reservation_id}`,
              )}
            >
              <Icon name="lease" />
              {ut(
                language,
                reservation === null ? "new_lease" : "new_lease_from_res",
              )}
            </a>
          )}
          {draft !== null && may("leases.read") && (
            <a
              className="ui-btn primary"
              href={hashForPage("leases", draft.lease_id)}
            >
              <Icon name="lease" />
              {ut(language, "open_draft")}
            </a>
          )}
          {current !== null && may("leases.read") && (
            <a
              className="ui-btn primary"
              href={hashForPage("leases", current.lease_id)}
            >
              <Icon name="lease" />
              {ut(language, "open_lease")}
            </a>
          )}
          {reservation !== null && may("reservations.read") && (
            <a
              className="ui-btn"
              href={hashForPage("reservations", reservation.reservation_id)}
            >
              <Icon name="calendar" />
              {ut(language, "open_reservation")}
            </a>
          )}
          {manage && (
            <>
              <button
                className="ui-btn"
                onClick={() => {
                  setNotice(null);
                  setWarning(null);
                  setDialog("status");
                }}
                type="button"
              >
                <Icon name="swap" />
                {ut(language, "change_status")}
              </button>
              <button
                className="ui-btn"
                onClick={() => {
                  setNotice(null);
                  setWarning(null);
                  setDialog("update");
                }}
                type="button"
              >
                <Icon name="swap" />
                {ut(language, "update_unit")}
              </button>
            </>
          )}
        </div>
      </div>
      {warning !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{warning}</p>
        </div>
      )}
      {notice !== null && (
        <div className="ui-notice ok" role="status">
          <Icon name="check" />
          <p>{notice}</p>
        </div>
      )}
      <div className="ui-split">
        <div className="ui-stack">
          <section aria-labelledby="unit-details" className="ui-card">
            <h2 id="unit-details">{ut(language, "details")}</h2>
            <div
              aria-label={ut(language, "no_photo")}
              className="ui-photo"
              role="img"
            >
              <Icon name="units" />
              <span>{ut(language, "no_photo")}</span>
              <span className="ui-small">{ut(language, "photo_later")}</span>
            </div>
            <div className="ui-facts">
              {fact(ut(language, "floor"), floorText(language, unit.floor))}
              {fact(ut(language, "type"), type)}
              {fact(
                ut(language, "size"),
                unit.size_square_metres === null ? (
                  notRecorded
                ) : (
                  <span className="ui-num">
                    {ut(language, "m2", Number(unit.size_square_metres))}
                  </span>
                ),
              )}
              {fact(
                ut(language, "beds"),
                unit.bedrooms === null ? (
                  notRecorded
                ) : (
                  <span className="ui-num">{unit.bedrooms}</span>
                ),
              )}
              {fact(
                ut(language, "baths"),
                unit.bathrooms === null ? (
                  notRecorded
                ) : (
                  <span className="ui-num">{unit.bathrooms}</span>
                ),
              )}
              {features.map((item) =>
                fact(
                  khmer && item.name_km !== null ? item.name_km : item.name_en,
                  ut(
                    language,
                    unit.room_feature_ids.includes(item.item_id)
                      ? "has"
                      : "hasnt",
                  ),
                ),
              )}
              {fact(
                ut(language, "view"),
                itemName(lists, unit.view_item_id, khmer) ?? notRecorded,
              )}
              {fact(
                ut(language, "kitchen"),
                itemName(lists, unit.kitchen_item_id, khmer) ?? notRecorded,
              )}
            </div>
            {unit.notes !== null && <p className="ui-small">{unit.notes}</p>}
            <UnitInventoryPanel
              api={unitApi}
              key={unit.unit_id}
              onSaved={load}
              propertyId={propertyId}
              unitId={unit.unit_id}
            />
          </section>
        </div>
        <div className="ui-stack">
          {now}
          <section aria-labelledby="unit-past" className="ui-card">
            <h2 id="unit-past">{ut(language, "past_leases")}</h2>
            {past.length === 0 ? (
              <p className="ui-small ui-muted">
                {leases === null
                  ? ut(language, "a_unknown")
                  : ut(language, "no_past")}
              </p>
            ) : (
              <ul className="ui-apps">
                {past.map((lease) => (
                  <li key={lease.lease_id}>
                    <span>
                      <b>{lease.primary_tenant_name}</b>
                      <small className="ui-num">
                        {dayText(lease.start_date)} –{" "}
                        {dayText(
                          lease.status === "TERMINATED"
                            ? lease.actual_termination_date
                            : lease.end_date,
                        )}{" "}
                        · {money(lease.monthly_rent_usd_cents)}
                      </small>
                    </span>
                    <LeaseChip
                      language={language}
                      lease={lease}
                      today={today}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="unit-meters" className="ui-card">
            <h2 id="unit-meters">{ut(language, "meters")}</h2>
            <p className="ui-small ui-muted">{ut(language, "meters_later")}</p>
          </section>
          <section aria-labelledby="unit-invoices" className="ui-card">
            <h2 id="unit-invoices">{ut(language, "invoices")}</h2>
            <p className="ui-small ui-muted">
              {ut(language, "invoices_later")}
            </p>
          </section>
          <section aria-labelledby="unit-history" className="ui-card">
            <h2 id="unit-history">{ut(language, "history")}</h2>
            {history.length === 0 ? (
              <p className="ui-small ui-muted">
                {ut(language, "history_none")}
              </p>
            ) : (
              <ol className="ui-timeline">
                {history.map((line, index) => (
                  <li key={`${line.at}-${String(index)}`}>
                    <div>
                      {line.text}
                      <small className="ui-num">{when(line.at)}</small>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
      {dialog === "update" && lists !== null && (
        <UpdateUnitDialog
          api={unitApi}
          language={language}
          lists={lists}
          onClose={() => {
            setDialog(null);
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(ut(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setNotice(ut(language, "saved", saved.unit_number));
            onChanged(saved);
            load();
          }}
          unit={unit}
        />
      )}
      {dialog === "status" && (
        <ChangeStatusDialog
          api={unitApi}
          blocked={
            current !== null || unit.status === "OCCUPIED"
              ? "lease"
              : reservation !== null || unit.status === "RESERVED"
                ? "reservation"
                : null
          }
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(ut(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setNotice(
              ut(
                language,
                "status_saved",
                saved.unit_number,
                ut(language, `s_${saved.status}`),
              ),
            );
            onChanged(saved);
            load();
          }}
          unit={unit}
        />
      )}
    </>
  );
}
