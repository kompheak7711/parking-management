// V1-058 R2: the Customer page (DESIGN.md "Customers (round 2)"). Left: Contact and identity,
// Leases and Reservations, the Customer Account Ledger (read only). Right: Money, Unpaid
// Invoices and Latest Receipts (step R5), History.

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import type {
  CustomerApi,
  CustomerDetail as CustomerRecord,
  CustomerHistoryEvent,
  VehicleResource,
} from "../customerClient";
import {
  type CustomerLedgerApi,
  type LedgerPosition,
  ledgerMoney,
} from "../customerLedgerClient";
import type { LeaseResource } from "../leaseClient";
import { dayText, momentText, todayInPhnomPenh } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import { openPageInAddress } from "../shell/useHashPage";
import { Chip, type Tone } from "../shell/ui";
import type { Language } from "../signInText";
import {
  DeactivateDialog,
  EditContactDialog,
  VehicleDialog,
} from "./CustomerDialogs";
import { KindChip } from "./CustomersList";
import type { CustomerCommandGate } from "./commands";
import { ct, vehicleTypeText } from "./text";
import {
  CustomersData,
  isCurrentLease,
  leasesOf,
  roleOn,
  standingOf,
} from "./customersData";

type LeaseKind = "current" | "draft" | "ended" | "terminated" | "cancelled";

function leaseKind(lease: LeaseResource, today: string): LeaseKind {
  if (lease.status === "DRAFTED") return "draft";
  if (lease.status === "CANCELLED") return "cancelled";
  if (lease.status === "TERMINATED") return "terminated";
  return isCurrentLease(lease, today) ? "current" : "ended";
}

const LEASE_TONES: Record<LeaseKind, Tone> = {
  current: "ok",
  draft: "info",
  ended: "neutral",
  terminated: "neutral",
  cancelled: "neutral",
};

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

function historyText(language: Language, event: CustomerHistoryEvent): string {
  if (event.action === "customer.created") return ct(language, "h_created");
  if (event.action === "customer.updated") return ct(language, "h_updated");
  if (event.action === "customer.deactivated")
    return ct(language, "h_deactivated", event.reason);
  return ct(language, "h_other", event.action);
}

export interface CustomerDetailProps {
  language: Language;
  customerId: string;
  propertyId: string;
  actorId: string;
  customerApi: CustomerApi;
  ledgerApi: CustomerLedgerApi;
  data: Pick<CustomersData, "leases" | "reservations">;
  capabilities: ReadonlySet<string> | null;
  /** Opens this Customer in the Account Ledger below the page; null when it is not shown. */
  onOpenLedger: ((customerId: string) => void) | null;
  gate: CustomerCommandGate;
  /** A saved change; the list reads the Customers again. */
  onChanged: () => void;
  /** A line to show first, such as "Sok Dara was added." */
  firstNotice?: string | null;
}

export function CustomerDetail({
  language,
  customerId,
  propertyId,
  actorId,
  customerApi,
  ledgerApi,
  data,
  capabilities,
  onOpenLedger,
  gate,
  onChanged,
  firstNotice = null,
}: CustomerDetailProps) {
  const [customer, setCustomer] = useState<CustomerRecord | null>(null);
  const [missing, setMissing] = useState(false);
  // Undefined while it loads; null when it could not be read.
  const [position, setPosition] = useState<LedgerPosition | null | undefined>(
    undefined,
  );
  const [dialog, setDialog] = useState<
    "edit" | "deactivate" | "vehicle" | null
  >(null);
  // Parking Step 4: the Customer's vehicles; undefined while loading, null when unreadable.
  const [vehicles, setVehicles] = useState<
    VehicleResource[] | null | undefined
  >(undefined);
  const [editingVehicle, setEditingVehicle] = useState<VehicleResource | null>(
    null,
  );
  const [notice, setNotice] = useState<string | null>(firstNotice);
  const [warning, setWarning] = useState<string | null>(null);
  const sequence = useRef(0);
  const today = todayInPhnomPenh();
  const may = (capability: string) =>
    capabilities === null || capabilities.has(capability);

  const load = useCallback(() => {
    const operation = ++sequence.current;
    const controller = new AbortController();
    void customerApi
      .get(customerId)
      .then((loaded) => {
        if (operation !== sequence.current) return;
        setCustomer(loaded);
        setMissing(false);
      })
      .catch(() => {
        if (operation === sequence.current) setMissing(true);
      });
    // Parking Step 4: the vehicles, read apart so a failure leaves the rest of the page.
    void Promise.resolve()
      .then(() => customerApi.listVehicles(customerId))
      .then((loaded) => {
        if (operation === sequence.current) setVehicles(loaded);
      })
      .catch(() => {
        if (operation === sequence.current) setVehicles(null);
      });
    // One ledger line is enough: every page carries the Customer's position.
    void ledgerApi
      .read(
        { section: "history", customerId, limit: 1 },
        { actorId, propertyId, signal: controller.signal },
      )
      .then((reply) => {
        if (operation !== sequence.current) return;
        setPosition(reply.section === "customers" ? null : reply.position);
      })
      .catch(() => {
        if (operation === sequence.current) setPosition(null);
      });
    return () => {
      controller.abort();
    };
  }, [actorId, customerApi, customerId, ledgerApi, propertyId]);

  useEffect(() => {
    setCustomer(null);
    setPosition(undefined);
    setVehicles(undefined);
    return load();
  }, [load]);

  const back = (
    <button
      className="ui-crumb"
      onClick={() => {
        openPageInAddress("customers");
      }}
      type="button"
    >
      <Icon name="back" small />
      {ct(language, "back")}
    </button>
  );

  if (missing) {
    return (
      <>
        {back}
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{ct(language, "missing")}</p>
        </div>
      </>
    );
  }
  if (customer === null) {
    return (
      <>
        {back}
        <p className="ui-muted" role="status">
          {ct(language, "loading")}
        </p>
      </>
    );
  }

  const known = data.leases !== null && data.reservations !== null;
  const standing = standingOf(data, customerId, today);
  const leases = leasesOf(data.leases, customerId).sort((left, right) =>
    (right.start_date ?? right.created_at).localeCompare(
      left.start_date ?? left.created_at,
    ),
  );
  const reservations = (data.reservations ?? []).filter(
    (reservation) => reservation.customer_id === customerId,
  );
  const sub = [
    standing.role === null ? null : ct(language, `role_${standing.role}`),
    standing.unitNumber,
  ]
    .filter((part) => part !== null)
    .join(" · ");
  const none = <span className="ui-muted">—</span>;
  const unitLink = (unitId: string, unitNumber: string) =>
    may("units.read") ? (
      <a className="ui-no ui-num" href={hashForPage("units", unitId)}>
        {unitNumber}
      </a>
    ) : (
      <b className="ui-num">{unitNumber}</b>
    );
  const pet = position?.pet_deposit_usd_cents ?? "0";

  return (
    <>
      {back}
      <div className="ui-head">
        <div>
          <div className="ui-hrow">
            <h2>{customer.legal_name}</h2>
            {known && <KindChip kind={standing.kind} language={language} />}
            {!customer.active && (
              <Chip tone="err">{ct(language, "deactivated")}</Chip>
            )}
          </div>
          {sub !== "" && <p>{sub}</p>}
        </div>
        <div className="ui-actions">
          {customer.active && customer.can_manage && (
            <button
              className="ui-btn primary"
              onClick={() => {
                setNotice(null);
                setWarning(null);
                setDialog("edit");
              }}
              type="button"
            >
              <Icon name="customers" />
              {ct(language, "edit")}
            </button>
          )}
          {onOpenLedger !== null && position !== null && (
            <button
              className="ui-btn"
              onClick={() => {
                onOpenLedger(customerId);
              }}
              type="button"
            >
              <Icon name="invoice" />
              {ct(language, "open_ledger")}
            </button>
          )}
          {customer.active && customer.can_deactivate && (
            <button
              className="ui-btn"
              onClick={() => {
                setNotice(null);
                setWarning(null);
                setDialog("deactivate");
              }}
              type="button"
            >
              <Icon name="x" />
              {ct(language, "deactivate")}
            </button>
          )}
        </div>
      </div>
      {(customer.can_manage || customer.can_deactivate) &&
        customer.active &&
        !gate.open && (
          <div className="ui-notice warn" role="status">
            <Icon name="alert" />
            <p>{ct(language, "waiting_check")}</p>
          </div>
        )}
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
          <section aria-labelledby="customer-contact" className="ui-card">
            <h2 id="customer-contact">{ct(language, "contact")}</h2>
            <Kv
              rows={[
                [ct(language, "phone"), customer.phone_number ?? none],
                [ct(language, "email"), customer.email_address ?? none],
                [ct(language, "address"), customer.contact_address ?? none],
                [
                  ct(language, "dob"),
                  customer.date_of_birth === null ? (
                    none
                  ) : (
                    <span className="ui-num">
                      {dayText(customer.date_of_birth)}
                    </span>
                  ),
                ],
                [
                  ct(language, "gender"),
                  customer.gender === null
                    ? none
                    : ct(language, `g_${customer.gender}`),
                ],
                [ct(language, "nationality"), customer.nationality ?? none],
                [
                  ct(language, "idno"),
                  customer.id_document_number === null ? (
                    none
                  ) : (
                    <span className="ui-num">
                      {customer.id_document_number}
                    </span>
                  ),
                ],
                [ct(language, "memo"), customer.memo ?? none],
              ]}
            />
            <p className="ui-small ui-muted">{ct(language, "contact_note")}</p>
          </section>
          <section aria-labelledby="customer-vehicles" className="ui-card">
            <div className="ui-chead">
              <h2 id="customer-vehicles">{ct(language, "vehicles")}</h2>
              {customer.can_manage && customer.active && (
                <button
                  className="ui-btn"
                  onClick={() => {
                    setEditingVehicle(null);
                    setDialog("vehicle");
                  }}
                  type="button"
                >
                  <Icon name="plus" />
                  {ct(language, "add_vehicle")}
                </button>
              )}
            </div>
            {vehicles === undefined ? null : vehicles === null ? (
              <p className="ui-muted">{ct(language, "v_failed")}</p>
            ) : vehicles.length === 0 ? (
              <p className="ui-muted">{ct(language, "v_none")}</p>
            ) : (
              <ul className="ui-plain">
                {vehicles.map((item) => (
                  <li className="ui-line" key={item.vehicle_id}>
                    <span>
                      <b className="ui-num">{item.plate_text}</b>
                      {" · "}
                      <span>
                        {vehicleTypeText(language, item.vehicle_type)}
                      </span>
                    </span>
                    {customer.can_manage && customer.active && (
                      <button
                        className="ui-btn"
                        onClick={() => {
                          setEditingVehicle(item);
                          setDialog("vehicle");
                        }}
                        type="button"
                      >
                        {ct(language, "v_edit")}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="ui-small ui-muted">{ct(language, "v_note")}</p>
          </section>
          <section aria-labelledby="customer-rels" className="ui-card">
            <h2 id="customer-rels">{ct(language, "rels")}</h2>
            {!known ? (
              <p className="ui-small ui-muted">
                {ct(language, "rels_unknown")}
              </p>
            ) : leases.length === 0 && reservations.length === 0 ? (
              <p className="ui-small ui-muted">{ct(language, "no_rels")}</p>
            ) : (
              <ul className="ui-apps">
                {reservations.map((reservation) => (
                  <li key={reservation.reservation_id}>
                    <span>
                      <b>
                        {unitLink(reservation.unit_id, reservation.unit_number)}{" "}
                        · {ct(language, "role_res")}
                      </b>
                      <small className="ui-num">
                        {ct(
                          language,
                          "reserved_until",
                          dayText(reservation.effective_expiration_date),
                        )}
                      </small>
                    </span>
                    <Chip icon="check" tone="ok">
                      {ct(language, "rs_active")}
                    </Chip>
                  </li>
                ))}
                {leases.map((lease) => {
                  const kind = leaseKind(lease, today);
                  return (
                    <li key={lease.lease_id}>
                      <span>
                        <b>
                          {unitLink(lease.unit_id, lease.unit_number)} ·{" "}
                          {ct(language, `role_${roleOn(lease, customerId)}`)}
                        </b>
                        <small className="ui-num">
                          {dayText(lease.start_date)} –{" "}
                          {dayText(
                            lease.status === "TERMINATED"
                              ? lease.actual_termination_date
                              : lease.end_date,
                          )}
                        </small>
                      </span>
                      <Chip
                        icon={kind === "current" ? "check" : undefined}
                        tone={LEASE_TONES[kind]}
                      >
                        {ct(language, `lk_${kind}`)}
                      </Chip>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="ui-small ui-muted">{ct(language, "rels_note")}</p>
          </section>
          <section aria-labelledby="customer-ledger" className="ui-card">
            <div className="ui-chead">
              <h2 id="customer-ledger">{ct(language, "ledger")}</h2>
              <Chip tone="neutral">{ct(language, "readonly")}</Chip>
            </div>
            <p className="ui-small">{ct(language, "ledger_note")}</p>
            {onOpenLedger !== null && position !== null && (
              <div className="ui-qa">
                <button
                  className="ui-btn"
                  onClick={() => {
                    onOpenLedger(customerId);
                  }}
                  type="button"
                >
                  {ct(language, "open_ledger")}
                </button>
              </div>
            )}
          </section>
        </div>
        <div className="ui-stack">
          <section aria-labelledby="customer-money" className="ui-card">
            <h2 id="customer-money">{ct(language, "money")}</h2>
            {position === undefined ? (
              <p className="ui-small ui-muted" role="status">
                {ct(language, "loading")}
              </p>
            ) : position === null ? (
              <p className="ui-small ui-muted">
                {ct(language, "money_unknown")}
              </p>
            ) : (
              <Kv
                rows={[
                  [
                    ct(language, "unpaid"),
                    <b className="ui-num">
                      {ledgerMoney(position.total_owed_usd_cents)}
                    </b>,
                  ],
                  [
                    ct(language, "credit"),
                    <span>
                      <span className="ui-num">
                        {ledgerMoney(position.credit_usd_cents)}
                      </span>
                      <span className="ui-sub2">
                        {ct(language, "credit_note")}
                      </span>
                    </span>,
                  ],
                  [
                    ct(language, "security"),
                    <span>
                      <span className="ui-num">
                        {ledgerMoney(position.security_deposit_usd_cents)}
                      </span>
                      <span className="ui-sub2">
                        {ct(language, "dep_note")}
                      </span>
                    </span>,
                  ],
                  ...(/^0+$/.test(pet)
                    ? []
                    : ([
                        [
                          ct(language, "pet"),
                          <span>
                            <span className="ui-num">{ledgerMoney(pet)}</span>
                            <span className="ui-sub2">
                              {ct(language, "pet_note")}
                            </span>
                          </span>,
                        ],
                      ] as [string, ReactNode][])),
                ]}
              />
            )}
          </section>
          <section aria-labelledby="customer-invoices" className="ui-card">
            <h2 id="customer-invoices">
              {ct(language, "open_invoices")} · {ct(language, "receipts")}
            </h2>
            <p className="ui-small ui-muted">
              {ct(language, "invoices_later")}
            </p>
          </section>
          <section aria-labelledby="customer-history" className="ui-card">
            <h2 id="customer-history">{ct(language, "history")}</h2>
            {customer.audit_history.length === 0 ? (
              <p className="ui-small ui-muted">
                {ct(language, "history_none")}
              </p>
            ) : (
              <ol className="ui-timeline">
                {customer.audit_history.map((event) => (
                  <li key={event.event_id}>
                    <div>
                      {historyText(language, event)}
                      <small className="ui-num">
                        {momentText(event.occurred_at)}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
      {dialog === "edit" && (
        <EditContactDialog
          api={customerApi}
          customer={customer}
          gate={gate}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(ct(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setNotice(ct(language, "saved_edit", saved.legal_name));
            onChanged();
            load();
          }}
          propertyId={propertyId}
        />
      )}
      {dialog === "vehicle" && (
        <VehicleDialog
          api={customerApi}
          customer={customer}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onSaved={(saved, added) => {
            setDialog(null);
            setNotice(
              ct(language, added ? "v_added" : "v_saved", saved.plate_text),
            );
            load();
          }}
          propertyId={propertyId}
          vehicle={editingVehicle}
        />
      )}
      {dialog === "deactivate" && (
        <DeactivateDialog
          api={customerApi}
          customer={customer}
          gate={gate}
          language={language}
          onClose={() => {
            setDialog(null);
          }}
          onConflict={() => {
            setDialog(null);
            setWarning(ct(language, "conflict"));
            load();
          }}
          onSaved={(saved) => {
            setDialog(null);
            setNotice(ct(language, "saved_deactivated", saved.legal_name));
            onChanged();
            load();
          }}
          propertyId={propertyId}
        />
      )}
    </>
  );
}
